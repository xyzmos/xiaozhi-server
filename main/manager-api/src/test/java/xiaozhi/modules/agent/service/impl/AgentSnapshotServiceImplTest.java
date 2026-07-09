package xiaozhi.modules.agent.service.impl;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import java.lang.reflect.Method;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Date;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

import org.junit.jupiter.api.Test;
import org.mockito.InOrder;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.transaction.annotation.Transactional;

import xiaozhi.common.utils.JsonUtils;
import xiaozhi.modules.agent.Enums.AgentSnapshotField;
import xiaozhi.modules.agent.dao.AgentDao;
import xiaozhi.modules.agent.dao.AgentSnapshotDao;
import xiaozhi.modules.agent.dao.AgentTagDao;
import xiaozhi.modules.agent.dto.AgentSnapshotDataDTO;
import xiaozhi.modules.agent.dto.AgentSnapshotPageDTO;
import xiaozhi.modules.agent.dto.AgentSnapshotTagDTO;
import xiaozhi.modules.agent.dto.AgentUpdateDTO;
import xiaozhi.modules.agent.dto.ContextProviderDTO;
import xiaozhi.modules.agent.entity.AgentEntity;
import xiaozhi.modules.agent.entity.AgentSnapshotEntity;
import xiaozhi.modules.agent.entity.AgentTagEntity;
import xiaozhi.modules.agent.service.AgentContextProviderService;
import xiaozhi.modules.agent.service.AgentSnapshotService;
import xiaozhi.modules.agent.vo.AgentSnapshotVO;
import xiaozhi.modules.agent.vo.AgentInfoVO;
import xiaozhi.modules.correctword.service.CorrectWordFileService;

class AgentSnapshotServiceImplTest {

    @Test
    @SuppressWarnings("unchecked")
    void normalizeSortedJsonListTreatsDtoAndMapShapesEqually() throws Exception {
        AgentSnapshotServiceImpl service = new AgentSnapshotServiceImpl(null, null, null, null, null, null, null, null,
                null, null);
        Method method = AgentSnapshotServiceImpl.class.getDeclaredMethod("normalizeSortedJsonList", List.class);
        method.setAccessible(true);

        ContextProviderDTO dto = new ContextProviderDTO();
        dto.setUrl("https://example.com/context");
        dto.setHeaders(Map.of("Authorization", "Bearer token"));

        Map<String, Object> map = new LinkedHashMap<>();
        map.put("headers", Map.of("Authorization", "Bearer token"));
        map.put("url", "https://example.com/context");

        assertEquals(method.invoke(service, List.of(dto)), method.invoke(service, List.of(map)));
    }

    @Test
    void redactSnapshotDataMasksSensitiveFunctionAndHeaderValues() throws Exception {
        AgentSnapshotServiceImpl service = new AgentSnapshotServiceImpl(null, null, null, null, null, null, null, null,
                null, null);
        Method method = AgentSnapshotServiceImpl.class.getDeclaredMethod("redactSnapshotData",
                AgentSnapshotDataDTO.class);
        method.setAccessible(true);

        AgentSnapshotDataDTO data = new AgentSnapshotDataDTO();
        AgentUpdateDTO.FunctionInfo function = new AgentUpdateDTO.FunctionInfo();
        function.setPluginId("rag");
        function.setParamInfo(Map.of("api_key", "secret-key", "max_tokens", 32));
        ContextProviderDTO provider = new ContextProviderDTO();
        provider.setUrl("https://example.com/context");
        provider.setHeaders(Map.of("Authorization", "Bearer secret-token", "Accept", "application/json"));
        data.setFunctions(List.of(function));
        data.setContextProviders(List.of(provider));

        AgentSnapshotDataDTO redacted = (AgentSnapshotDataDTO) method.invoke(service, data);
        String json = JsonUtils.toJsonString(redacted);

        assertFalse(json.contains("secret-key"));
        assertFalse(json.contains("secret-token"));
        assertTrue(json.contains("__SNAPSHOT_SECRET_REDACTED__"));
        assertTrue(json.contains("max_tokens"));
        assertTrue(json.contains("application/json"));
    }

    @Test
    void preserveCurrentSensitiveValuesKeepsCurrentSecretsWhenRestoringSnapshot() throws Exception {
        AgentSnapshotServiceImpl service = new AgentSnapshotServiceImpl(null, null, null, null, null, null, null, null,
                null, null);
        Method method = AgentSnapshotServiceImpl.class.getDeclaredMethod("preserveCurrentSensitiveValues",
                AgentSnapshotDataDTO.class, AgentSnapshotDataDTO.class);
        method.setAccessible(true);

        AgentSnapshotDataDTO snapshot = buildSnapshot("old-key", "old-token", "old-value");
        AgentSnapshotDataDTO current = buildSnapshot("current-key", "current-token", "current-value");

        AgentSnapshotDataDTO restored = (AgentSnapshotDataDTO) method.invoke(service, snapshot, current);

        assertEquals("current-key", restored.getFunctions().get(0).getParamInfo().get("api_key"));
        assertEquals("old-value", restored.getFunctions().get(0).getParamInfo().get("description"));
        assertEquals("current-token", restored.getContextProviders().get(0).getHeaders().get("Authorization"));
    }

    @Test
    @SuppressWarnings("unchecked")
    void getChangedFieldsFollowsCentralFieldOrder() throws Exception {
        AgentSnapshotServiceImpl service = new AgentSnapshotServiceImpl(null, null, null, null, null, null, null, null,
                null, null);
        Method method = AgentSnapshotServiceImpl.class.getDeclaredMethod("getChangedFields",
                AgentSnapshotDataDTO.class, AgentUpdateDTO.class);
        method.setAccessible(true);

        AgentSnapshotDataDTO current = new AgentSnapshotDataDTO();
        current.setAgentName("old-name");
        current.setCorrectWordFileIds(List.of("b", "a"));

        AgentUpdateDTO pendingUpdate = new AgentUpdateDTO();
        pendingUpdate.setAgentName("new-name");
        pendingUpdate.setCorrectWordFileIds(List.of("a", "b"));
        AgentUpdateDTO.FunctionInfo function = new AgentUpdateDTO.FunctionInfo();
        function.setPluginId("rag");
        function.setParamInfo(Map.of("api_key", "secret-key"));
        pendingUpdate.setFunctions(List.of(function));

        List<String> changedFields = (List<String>) method.invoke(service, current, pendingUpdate);

        assertEquals(List.of(AgentSnapshotField.AGENT_NAME.getFieldName(),
                AgentSnapshotField.FUNCTIONS.getFieldName()), changedFields);
    }

    @Test
    @SuppressWarnings("unchecked")
    void tagIdsAreNotExposedAsIndependentSnapshotFields() throws Exception {
        AgentSnapshotServiceImpl service = new AgentSnapshotServiceImpl(null, null, null, null, null, null, null, null,
                null, null);
        Method method = AgentSnapshotServiceImpl.class.getDeclaredMethod("getChangedFields",
                AgentSnapshotDataDTO.class, AgentUpdateDTO.class);
        method.setAccessible(true);

        AgentSnapshotDataDTO current = new AgentSnapshotDataDTO();
        current.setTagNames(List.of("alpha", "beta"));

        AgentUpdateDTO pendingUpdate = new AgentUpdateDTO();
        pendingUpdate.setTagNames(List.of("beta", "alpha"));
        pendingUpdate.setTagIds(List.of("new-id"));

        List<String> changedFields = (List<String>) method.invoke(service, current, pendingUpdate);

        assertFalse(AgentSnapshotField.names().contains("tagIds"));
        assertFalse(changedFields.contains("tagIds"));
        assertTrue(changedFields.isEmpty());

        pendingUpdate.setTagNames(List.of("alpha", "gamma"));
        changedFields = (List<String>) method.invoke(service, current, pendingUpdate);

        assertEquals(List.of(AgentSnapshotField.TAG_NAMES.getFieldName()), changedFields);
    }

    @Test
    void tagOnlySavePathCreatesSnapshot() throws Exception {
        String controller = Files.readString(Path.of("src/main/java/xiaozhi/modules/agent/controller/AgentController.java"));
        String roleConfig = Files.readString(Path.of("../manager-web/src/views/roleConfig.vue"));

        assertTrue(controller.contains("agentService.updateAgentById(id, dto);"));
        assertFalse(controller.contains("agentService.updateAgentById(id, dto, false);"));
        assertTrue(roleConfig.contains("configData.tagNames = tagNames;"));
        assertFalse(roleConfig.contains("this.handleSaveAgentTags(agentId, tagNames)"));
    }

    @Test
    void firstAgentSaveKeepsInitialBaselineBeforePersistingNewState() {
        AgentDao agentDao = mock(AgentDao.class);
        AgentContextProviderService contextProviderService = mock(AgentContextProviderService.class);
        CorrectWordFileService correctWordFileService = mock(CorrectWordFileService.class);
        AgentSnapshotService snapshotService = mock(AgentSnapshotService.class);
        AgentServiceImpl service = new AgentServiceImpl(agentDao, null, null, null, null, null, null, null,
                null, null, contextProviderService, null, correctWordFileService, snapshotService);
        ReflectionTestUtils.setField(service, "baseDao", agentDao);

        String agentId = "agent-id";
        AgentEntity lockedAgent = new AgentEntity();
        lockedAgent.setId(agentId);
        AgentInfoVO currentAgent = new AgentInfoVO();
        currentAgent.setId(agentId);
        currentAgent.setAgentName("old-name");
        AgentUpdateDTO update = new AgentUpdateDTO();
        update.setAgentName("new-name");

        when(agentDao.selectByIdForUpdate(agentId)).thenReturn(lockedAgent);
        when(agentDao.selectAgentInfoById(agentId)).thenReturn(currentAgent);
        when(snapshotService.getCurrentVersionNo(agentId)).thenReturn(0);
        when(contextProviderService.getByAgentId(agentId)).thenReturn(null);
        when(correctWordFileService.getAgentCorrectWordFileIds(agentId)).thenReturn(List.of());
        when(agentDao.updateById(any())).thenReturn(1);

        service.updateAgentById(agentId, update);

        InOrder inOrder = inOrder(agentDao, snapshotService);
        inOrder.verify(snapshotService).createSnapshot(agentId, "initial");
        inOrder.verify(agentDao).updateById(argThat(agent -> "new-name".equals(agent.getAgentName())));
        inOrder.verify(snapshotService).createSnapshot(agentId, "config");
    }

    @Test
    void agentSnapshotFieldAppliesRestorableAgentFields() {
        AgentSnapshotDataDTO data = new AgentSnapshotDataDTO();
        data.setAgentName("restored-name");
        data.setLlmModelId("llm-new");
        data.setSystemPrompt("restored prompt");
        data.setSort(7);

        AgentEntity agent = new AgentEntity();
        for (AgentSnapshotField field : AgentSnapshotField.values()) {
            field.applyTo(agent, data);
        }

        assertEquals("restored-name", agent.getAgentName());
        assertEquals("llm-new", agent.getLlmModelId());
        assertEquals("restored prompt", agent.getSystemPrompt());
        assertEquals(7, agent.getSort());
    }

    @Test
    void restoreSnapshotRollsBackForAnyException() throws Exception {
        Method method = AgentSnapshotServiceImpl.class.getMethod("restoreSnapshot", String.class, String.class);

        Transactional transactional = method.getAnnotation(Transactional.class);

        assertNotNull(transactional);
        assertTrue(List.of(transactional.rollbackFor()).contains(Exception.class));
    }

    @Test
    void deleteSnapshotRollsBackForAnyException() throws Exception {
        Method method = AgentSnapshotServiceImpl.class.getMethod("deleteSnapshot", String.class, String.class);

        Transactional transactional = method.getAnnotation(Transactional.class);

        assertNotNull(transactional);
        assertTrue(List.of(transactional.rollbackFor()).contains(Exception.class));
    }

    @Test
    void snapshotInsertAllocatesVersionInSingleSqlStatement() throws Exception {
        String xml = normalizeWhitespace(Files.readString(Path.of("src/main/resources/mapper/agent/AgentSnapshotDao.xml")));
        String dao = Files.readString(Path.of("src/main/java/xiaozhi/modules/agent/dao/AgentSnapshotDao.java"));

        assertTrue(dao.contains("insertWithNextVersion"));
        assertTrue(xml.contains("<insert id=\"insertWithNextVersion\">"));
        assertTrue(xml.contains("INSERT INTO ai_agent_snapshot"));
        assertTrue(xml.contains("COALESCE(MAX(version_no), 0) + 1"));
        assertFalse(xml.contains("LAST_INSERT_ID"));
        assertFalse(xml.contains("ai_agent_snapshot_sequence"));
    }

    @Test
    void snapshotMigrationIsMergedIntoSingleChangeLog() throws Exception {
        String sql = Files.readString(Path.of("src/main/resources/db/changelog/202607071530.sql"));
        String master = Files.readString(Path.of("src/main/resources/db/changelog/db.changelog-master.yaml"));

        assertTrue(sql.contains("restore_from_snapshot_id"));
        assertTrue(sql.contains("restore_from_version_no"));
        assertTrue(sql.contains("idx_snapshot_user_created_at"));
        assertTrue(sql.contains("DEFAULT (JSON_OBJECT())"));
        assertTrue(master.contains("202607071530.sql"));
        assertFalse(master.contains("202607081150.sql"));
        assertFalse(master.contains("202607081230.sql"));
    }

    @Test
    void selectNextSnapshotLoadsRestoreTraceColumns() throws Exception {
        String xml = normalizeWhitespace(Files.readString(Path.of("src/main/resources/mapper/agent/AgentSnapshotDao.xml")));

        assertTrue(xml.contains("restore_from_snapshot_id AS restoreFromSnapshotId"));
        assertTrue(xml.contains("restore_from_version_no AS restoreFromVersionNo"));
    }

    @Test
    void retentionPruneSqlKeepsLatestVersions() throws Exception {
        String xml = Files.readString(Path.of("src/main/resources/mapper/agent/AgentSnapshotDao.xml"));

        assertTrue(xml.contains("deleteOlderThanKeepLimit"));
        assertTrue(xml.contains("ORDER BY version_no DESC"));
        assertTrue(xml.contains("LIMIT #{keepLimit}"));
    }

    @Test
    void agentInfoMapperLoadsFunctionsWithJoinInsteadOfNestedSelect() throws Exception {
        String xml = Files.readString(Path.of("src/main/resources/mapper/agent/AgentDao.xml"));

        assertTrue(xml.contains("LEFT JOIN ai_agent_plugin_mapping f ON f.agent_id = a.id"));
        assertFalse(xml.contains("selectAgentFunctionsByAgentId"));
        assertFalse(xml.contains("select=\"selectAgentFunctions"));
    }

    @Test
    void toVOIncludesRestoreTraceFields() throws Exception {
        AgentSnapshotServiceImpl service = new AgentSnapshotServiceImpl(null, null, null, null, null, null, null, null,
                null, null);
        Method method = AgentSnapshotServiceImpl.class.getDeclaredMethod("toVO",
                AgentSnapshotEntity.class, boolean.class);
        method.setAccessible(true);

        AgentSnapshotEntity entity = new AgentSnapshotEntity();
        entity.setId("snapshot-id");
        entity.setAgentId("agent-id");
        entity.setVersionNo(3);
        entity.setChangedFields("[]");
        entity.setSource("restore");
        entity.setRestoreFromSnapshotId("target-id");
        entity.setRestoreFromVersionNo(1);

        AgentSnapshotVO vo = (AgentSnapshotVO) method.invoke(service, entity, false);

        assertEquals("target-id", vo.getRestoreFromSnapshotId());
        assertEquals(1, vo.getRestoreFromVersionNo());
    }

    @Test
    void pageDoesNotCreateInitialSnapshotWhenAgentHasNoHistory() {
        AgentSnapshotDao snapshotDao = mock(AgentSnapshotDao.class);
        AgentDao agentDao = mock(AgentDao.class);
        AgentSnapshotServiceImpl service = new AgentSnapshotServiceImpl(snapshotDao, agentDao, null, null, null,
                null, null, null, null, null);

        when(snapshotDao.selectPage(any(), any())).thenReturn(new Page<AgentSnapshotEntity>(1, 10));

        service.page("agent-id", new AgentSnapshotPageDTO());

        verify(agentDao, never()).selectByIdForUpdate(any());
        verify(snapshotDao, never()).selectMaxVersionNo(any());
        verify(snapshotDao, never()).insertWithNextVersion(any());
        verify(snapshotDao, never()).deleteOlderThanKeepLimit(any(), anyInt());
    }

    @Test
    void getCurrentVersionNoReturnsPersistedMaxVersion() {
        AgentSnapshotDao snapshotDao = mock(AgentSnapshotDao.class);
        AgentSnapshotServiceImpl service = new AgentSnapshotServiceImpl(snapshotDao, null, null, null, null,
                null, null, null, null, null);

        when(snapshotDao.selectMaxVersionNo("agent-id")).thenReturn(7);

        assertEquals(7, service.getCurrentVersionNo("agent-id"));
    }

    @Test
    void createSnapshotStoresCurrentStateAsInitialVersionWhenHistoryIsEmpty() {
        AgentSnapshotDao snapshotDao = mock(AgentSnapshotDao.class);
        AgentDao agentDao = mock(AgentDao.class);
        AgentTagDao tagDao = mock(AgentTagDao.class);
        AgentContextProviderService contextProviderService = mock(AgentContextProviderService.class);
        CorrectWordFileService correctWordFileService = mock(CorrectWordFileService.class);
        AgentSnapshotServiceImpl service = new AgentSnapshotServiceImpl(snapshotDao, agentDao, tagDao, null, null,
                contextProviderService, null, null, null, correctWordFileService);

        AgentEntity lockedAgent = new AgentEntity();
        lockedAgent.setId("agent-id");
        AgentInfoVO agentInfo = new AgentInfoVO();
        agentInfo.setId("agent-id");
        agentInfo.setUserId(7L);
        agentInfo.setAgentName("agent");
        when(agentDao.selectByIdForUpdate("agent-id")).thenReturn(lockedAgent);
        when(agentDao.selectAgentInfoById("agent-id")).thenReturn(agentInfo);
        when(snapshotDao.selectLatestSnapshot("agent-id")).thenReturn(null);
        when(snapshotDao.insertWithNextVersion(any())).thenReturn(1);
        when(correctWordFileService.getAgentCorrectWordFileIds("agent-id")).thenReturn(List.of());
        when(contextProviderService.getByAgentId("agent-id")).thenReturn(null);
        when(tagDao.selectByAgentId("agent-id")).thenReturn(List.of());

        service.createSnapshot("agent-id", "config");

        verify(snapshotDao).insertWithNextVersion(argThat(snapshot -> "config".equals(snapshot.getSource())
                && snapshot.getVersionNo() == null
                && snapshot.getChangedFields().contains("initial")));
        verify(snapshotDao).deleteOlderThanKeepLimit("agent-id", 100);
    }

    @Test
    void restoreTagDoesNotReviveSoftDeletedSnapshotTagId() throws Exception {
        AgentTagDao tagDao = mock(AgentTagDao.class);
        AgentSnapshotServiceImpl service = new AgentSnapshotServiceImpl(null, null, tagDao, null, null, null, null, null,
                null, null);
        Method method = AgentSnapshotServiceImpl.class.getDeclaredMethod("restoreTag",
                AgentSnapshotTagDTO.class, Date.class);
        method.setAccessible(true);

        AgentTagEntity deletedTag = new AgentTagEntity();
        deletedTag.setId("deleted-tag-id");
        deletedTag.setTagName("archived");
        deletedTag.setDeleted(1);
        when(tagDao.selectById("deleted-tag-id")).thenReturn(deletedTag);
        when(tagDao.selectOne(any())).thenReturn(null);
        AtomicReference<AgentTagEntity> insertedTag = new AtomicReference<>();
        when(tagDao.insert(any())).thenAnswer(invocation -> {
            insertedTag.set(invocation.getArgument(0));
            return 1;
        });

        AgentSnapshotTagDTO snapshotTag = new AgentSnapshotTagDTO();
        snapshotTag.setId("deleted-tag-id");
        snapshotTag.setTagName("archived");

        String restoredTagId = (String) method.invoke(service, snapshotTag, new Date());

        verify(tagDao, never()).updateById(any());
        assertNotEquals("deleted-tag-id", restoredTagId);
        assertNotNull(insertedTag.get());
        assertEquals(restoredTagId, insertedTag.get().getId());
        assertEquals(0, insertedTag.get().getDeleted());
    }

    private AgentSnapshotDataDTO buildSnapshot(String apiKey, String authToken, String description) {
        AgentSnapshotDataDTO data = new AgentSnapshotDataDTO();

        AgentUpdateDTO.FunctionInfo function = new AgentUpdateDTO.FunctionInfo();
        function.setPluginId("rag");
        HashMap<String, Object> params = new HashMap<>();
        params.put("api_key", apiKey);
        params.put("description", description);
        function.setParamInfo(params);

        ContextProviderDTO provider = new ContextProviderDTO();
        provider.setUrl("https://example.com/context");
        provider.setHeaders(Map.of("Authorization", authToken));

        data.setFunctions(List.of(function));
        data.setContextProviders(List.of(provider));
        return data;
    }

    private String normalizeWhitespace(String value) {
        return value.replaceAll("\\s+", " ").trim();
    }
}
