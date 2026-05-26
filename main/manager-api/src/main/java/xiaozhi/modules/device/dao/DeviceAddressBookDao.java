package xiaozhi.modules.device.dao;

import java.util.List;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;

import xiaozhi.modules.device.entity.DeviceAddressBookEntity;

@Mapper
public interface DeviceAddressBookDao extends BaseMapper<DeviceAddressBookEntity> {

    /**
     * 获取设备通讯录列表
     */
    List<DeviceAddressBookEntity> getAddressBookList(@Param("macAddress") String macAddress);

    /**
     * 更新别名
     */
    void updateAlias(@Param("macAddress") String macAddress, @Param("targetMac") String targetMac, @Param("alias") String alias);

    /**
     * 更新权限
     */
    void updatePermission(@Param("macAddress") String macAddress, @Param("targetMac") String targetMac, @Param("hasPermission") Boolean hasPermission);
}