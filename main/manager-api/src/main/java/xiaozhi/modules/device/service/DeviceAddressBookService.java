package xiaozhi.modules.device.service;

import java.util.List;
import java.util.Map;

import xiaozhi.modules.device.entity.DeviceAddressBookEntity;

public interface DeviceAddressBookService {

    /**
     * 获取设备通讯录列表
     */
    List<DeviceAddressBookEntity> getAddressBookList(String macAddress);

    /**
     * 获取所有设备的通讯录（全局缓存用）
     */
    Map<String, Map<String, String>> getAllAddressBooks();

    /**
     * 更新别名
     */
    void updateAlias(String macAddress, String targetMac, String alias);

    /**
     * 更新权限
     */
    void updatePermission(String macAddress, String targetMac, Boolean hasPermission);

    /**
     * 添加或更新通讯录记录
     */
    void saveOrUpdate(String macAddress, String targetMac, String alias, Boolean hasPermission);

    /**
     * 刷新通讯录缓存
     */
    void refreshCache();

    /**
     * 根据昵称查找目标设备信息
     * @param callerMac 主叫方MAC地址
     * @param nickname 被叫方昵称
     * @return {targetMac: 目标MAC, callerNickname: 目标如何称呼主叫方}
     */
    Map<String, String> lookupByNickname(String callerMac, String nickname);
}