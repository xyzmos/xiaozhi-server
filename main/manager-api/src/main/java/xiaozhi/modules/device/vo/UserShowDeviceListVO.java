package xiaozhi.modules.device.vo;

import java.util.Date;

import com.fasterxml.jackson.annotation.JsonFormat;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

@Data
@Schema(description = "用户显示设备列表VO")
public class UserShowDeviceListVO {

    @Schema(description = "app版本")
    private String appVersion;

    @Schema(description = "绑定用户名称")
    private String bindUserName;

    @Schema(description = "设备型号")
    private String deviceType;

    @Schema(description = "设备型号(board)")
    private String board;

    @Schema(description = "设备唯一标识符")
    private String id;

    @Schema(description = "mac地址")
    private String macAddress;

    @Schema(description = "设备别名")
    private String alias;

    @Schema(description = "开启OTA")
    private Integer otaUpgrade;

    @Schema(description = "最近对话时间")
    private String recentChatTime;

    @Schema(description = "最后连接时间(UTC毫秒)")
    private Long lastConnectedAtTimestamp;

    @Schema(description = "绑定时间")
    @JsonFormat(shape = JsonFormat.Shape.STRING, pattern = "yyyy-MM-dd HH:mm:ss", timezone = "UTC")
    private Date createDate;

}