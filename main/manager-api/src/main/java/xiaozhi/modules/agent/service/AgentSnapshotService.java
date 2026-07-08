package xiaozhi.modules.agent.service;

import xiaozhi.common.page.PageData;
import xiaozhi.common.service.BaseService;
import xiaozhi.modules.agent.dto.AgentSnapshotPageDTO;
import xiaozhi.modules.agent.dto.AgentUpdateDTO;
import xiaozhi.modules.agent.entity.AgentSnapshotEntity;
import xiaozhi.modules.agent.vo.AgentSnapshotVO;

public interface AgentSnapshotService extends BaseService<AgentSnapshotEntity> {
    void createSnapshot(String agentId, String source, AgentUpdateDTO pendingUpdate);

    PageData<AgentSnapshotVO> page(String agentId, AgentSnapshotPageDTO params);

    AgentSnapshotVO getSnapshot(String agentId, String snapshotId);

    void restoreSnapshot(String agentId, String snapshotId);

    void deleteSnapshot(String agentId, String snapshotId);

    Integer getCurrentVersionNo(String agentId);

    void deleteByAgentId(String agentId);
}
