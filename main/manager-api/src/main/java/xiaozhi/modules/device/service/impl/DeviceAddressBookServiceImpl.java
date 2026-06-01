package xiaozhi.modules.device.service.impl;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

import org.apache.commons.lang3.StringUtils;
import org.springframework.stereotype.Service;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;

import xiaozhi.common.redis.RedisKeys;
import xiaozhi.common.redis.RedisUtils;
import xiaozhi.modules.device.dao.DeviceAddressBookDao;
import xiaozhi.modules.device.entity.DeviceAddressBookEntity;
import xiaozhi.modules.device.service.DeviceAddressBookService;
import xiaozhi.modules.device.service.DeviceService;

@Service
public class DeviceAddressBookServiceImpl implements DeviceAddressBookService {

    private final DeviceAddressBookDao deviceAddressBookDao;
    private final RedisUtils redisUtils;
    private final DeviceService deviceService;

    public DeviceAddressBookServiceImpl(DeviceAddressBookDao deviceAddressBookDao, RedisUtils redisUtils,
            DeviceService deviceService) {
        this.deviceAddressBookDao = deviceAddressBookDao;
        this.redisUtils = redisUtils;
        this.deviceService = deviceService;
    }

    @Override
    public List<DeviceAddressBookEntity> getAddressBookList(String macAddress) {
        return deviceAddressBookDao.getAddressBookList(macAddress);
    }

    @Override
    @SuppressWarnings("unchecked")
    public Map<String, Map<String, String>> getAllAddressBooks() {
        Object cached = redisUtils.get(RedisKeys.getAddressBookKey());
        if (cached != null) {
            return (Map<String, Map<String, String>>) cached;
        }
        refreshCache();
        return (Map<String, Map<String, String>>) redisUtils.get(RedisKeys.getAddressBookKey());
    }

    @Override
    public Map<String, String> lookupByNickname(String callerMac, String nickname) {
        Map<String, Map<String, String>> allBooks = getAllAddressBooks();
        Map<String, String> callerBook = allBooks.get(callerMac.toLowerCase());
        if (callerBook == null) {
            return null;
        }
        // 从缓存获取 targetMac，格式: "mac|permission"
        String targetMacWithPerm = callerBook.get(nickname);
        if (targetMacWithPerm == null) {
            return null;
        }
        // 解析 targetMac 和 permission
        String[] parts = targetMacWithPerm.split("\\|");
        String targetMac = parts[0];
        boolean hasPermission = parts.length > 1 && "1".equals(parts[1]);

        Map<String, String> targetBook = allBooks.get(targetMac.toLowerCase());
        if (targetBook == null) {
            return null;
        }
        // 检查双向关系：目标设备是否也添加了主叫方为联系人
        String callerNickname = targetBook.get(callerMac.toLowerCase());
        Map<String, String> result = new HashMap<>();
        result.put("targetMac", targetMac);
        result.put("callerNickname", callerNickname);
        result.put("hasPermission", hasPermission ? "true" : "false");
        return result;
    }

    @Override
    public void refreshCache() {
        Map<String, Map<String, String>> result = new HashMap<>();
        List<DeviceAddressBookEntity> allRecords = deviceAddressBookDao.selectList(null);
        Map<String, String> reverseMap = new HashMap<>();
        Map<String, Boolean> permissionMap = new HashMap<>();
        for (DeviceAddressBookEntity entity : allRecords) {
            String macA = entity.getMacAddress().toLowerCase();
            String macB = entity.getTargetMac().toLowerCase();
            String alias = entity.getAlias();
            Boolean hasPermission = entity.getHasPermission();
            if (alias != null && !alias.isEmpty()) {
                // 反向记录: (macB, macA) = B对A的称呼
                reverseMap.put(macB + ":" + macA, alias);
            }
            // 记录 A 对 B 是否有权限呼叫
            permissionMap.put(macA + ":" + macB, hasPermission != null && hasPermission);
        }
        for (DeviceAddressBookEntity entity : allRecords) {
            String macA = entity.getMacAddress().toLowerCase();
            String macB = entity.getTargetMac().toLowerCase();
            String aliasAtoB = entity.getAlias();
            result.computeIfAbsent(macA, k -> new HashMap<>());
            result.computeIfAbsent(macB, k -> new HashMap<>());
            if (aliasAtoB != null && !aliasAtoB.isEmpty()) {
                // A对B的映射: nickname -> macB|permission
                Boolean perm = entity.getHasPermission();
                String permStr = (perm != null && perm) ? "1" : "0";
                result.get(macA).put(aliasAtoB, macB + "|" + permStr);
            }
            // B对A的映射: macA -> nickname（查反向记录）
            String aliasBtoA = reverseMap.get(macA + ":" + macB);
            if (aliasBtoA != null && !aliasBtoA.isEmpty()) {
                result.get(macB).put(macA, aliasBtoA);
            }
        }
        redisUtils.set(RedisKeys.getAddressBookKey(), result);
    }

    @Override
    public void updateAlias(String macAddress, String targetMac, String alias) {
        deviceAddressBookDao.updateAlias(macAddress, targetMac, alias);
        refreshCache();
    }

    @Override
    public void updatePermission(String macAddress, String targetMac, Boolean hasPermission) {
        deviceAddressBookDao.updatePermission(macAddress, targetMac, hasPermission);
        refreshCache();
    }

    @Override
    public void saveOrUpdate(String macAddress, String targetMac, String alias, Boolean hasPermission) {
        QueryWrapper<DeviceAddressBookEntity> wrapper = new QueryWrapper<>();
        wrapper.eq("mac_address", macAddress).eq("target_mac", targetMac);
        DeviceAddressBookEntity record = deviceAddressBookDao.selectOne(wrapper);
        if (record == null) {
            DeviceAddressBookEntity entity = new DeviceAddressBookEntity();
            entity.setMacAddress(macAddress);
            entity.setTargetMac(targetMac);
            // 如果 alias 为空，就用默认使用设备名称
            if (StringUtils.isBlank(alias)) {
                alias = deviceService.getDeviceByMacAddress(targetMac).getAlias();
            }
            entity.setAlias(alias);
            entity.setHasPermission(hasPermission);
            deviceAddressBookDao.insert(entity);
        } else {
            if (alias != null) {
                deviceAddressBookDao.updateAlias(macAddress, targetMac, alias);
            }
            if (hasPermission != null) {
                deviceAddressBookDao.updatePermission(macAddress, targetMac, hasPermission);
            }
        }
        refreshCache();
    }
}