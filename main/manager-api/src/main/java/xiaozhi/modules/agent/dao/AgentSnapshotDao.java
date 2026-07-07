package xiaozhi.modules.agent.dao;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

import xiaozhi.common.dao.BaseDao;
import xiaozhi.modules.agent.entity.AgentSnapshotEntity;

@Mapper
public interface AgentSnapshotDao extends BaseDao<AgentSnapshotEntity> {
    Integer selectMaxVersionNo(@Param("agentId") String agentId);

    AgentSnapshotEntity selectNextSnapshot(@Param("agentId") String agentId, @Param("versionNo") Integer versionNo);
}
