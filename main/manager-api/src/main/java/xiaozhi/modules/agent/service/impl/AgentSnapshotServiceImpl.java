package xiaozhi.modules.agent.service.impl;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.TreeMap;
import java.util.UUID;
import java.util.function.Function;
import java.util.stream.Collectors;

import org.apache.commons.lang3.StringUtils;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.core.metadata.OrderItem;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.fasterxml.jackson.core.type.TypeReference;

import lombok.AllArgsConstructor;
import xiaozhi.common.constant.Constant;
import xiaozhi.common.exception.ErrorCode;
import xiaozhi.common.exception.RenException;
import xiaozhi.common.page.PageData;
import xiaozhi.common.service.impl.BaseServiceImpl;
import xiaozhi.common.utils.JsonUtils;
import xiaozhi.modules.agent.dao.AgentDao;
import xiaozhi.modules.agent.dao.AgentSnapshotDao;
import xiaozhi.modules.agent.dao.AgentTagDao;
import xiaozhi.modules.agent.dao.AgentTagRelationDao;
import xiaozhi.modules.agent.dto.AgentSnapshotDataDTO;
import xiaozhi.modules.agent.dto.AgentSnapshotPageDTO;
import xiaozhi.modules.agent.dto.AgentSnapshotTagDTO;
import xiaozhi.modules.agent.dto.AgentUpdateDTO;
import xiaozhi.modules.agent.entity.AgentContextProviderEntity;
import xiaozhi.modules.agent.entity.AgentEntity;
import xiaozhi.modules.agent.entity.AgentPluginMapping;
import xiaozhi.modules.agent.entity.AgentSnapshotEntity;
import xiaozhi.modules.agent.entity.AgentTagEntity;
import xiaozhi.modules.agent.entity.AgentTagRelationEntity;
import xiaozhi.modules.agent.Enums.AgentSnapshotField;
import xiaozhi.modules.agent.service.AgentChatHistoryService;
import xiaozhi.modules.agent.service.AgentContextProviderService;
import xiaozhi.modules.agent.service.AgentPluginMappingService;
import xiaozhi.modules.agent.service.AgentSnapshotService;
import xiaozhi.modules.agent.service.AgentTagService;
import xiaozhi.modules.agent.vo.AgentInfoVO;
import xiaozhi.modules.agent.vo.AgentSnapshotVO;
import xiaozhi.modules.correctword.service.CorrectWordFileService;
import xiaozhi.modules.model.entity.ModelConfigEntity;
import xiaozhi.modules.model.service.ModelConfigService;
import xiaozhi.modules.security.user.SecurityUser;

@Service
@AllArgsConstructor
public class AgentSnapshotServiceImpl extends BaseServiceImpl<AgentSnapshotDao, AgentSnapshotEntity>
        implements AgentSnapshotService {
    private static final int MAX_SNAPSHOTS_PER_AGENT = 100;
    private static final TypeReference<List<String>> STRING_LIST_TYPE = new TypeReference<>() {
    };
    private static final TypeReference<HashMap<String, Object>> PARAM_INFO_TYPE = new TypeReference<>() {
    };
    private static final TypeReference<Map<String, Object>> OBJECT_MAP_TYPE = new TypeReference<>() {
    };
    private static final String SECRET_PLACEHOLDER = "__SNAPSHOT_SECRET_REDACTED__";

    private final AgentSnapshotDao agentSnapshotDao;
    private final AgentDao agentDao;
    private final AgentTagDao agentTagDao;
    private final AgentTagRelationDao agentTagRelationDao;
    private final AgentPluginMappingService agentPluginMappingService;
    private final AgentContextProviderService agentContextProviderService;
    private final AgentTagService agentTagService;
    private final AgentChatHistoryService agentChatHistoryService;
    private final ModelConfigService modelConfigService;
    private final CorrectWordFileService correctWordFileService;

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void createSnapshot(String agentId, String source) {
        lockAgent(agentId);
        AgentInfoVO agent = getAgentInfo(agentId);
        AgentSnapshotDataDTO snapshotData = buildSnapshotData(agent);
        AgentSnapshotEntity previousSnapshot = agentSnapshotDao.selectLatestSnapshot(agentId);
        List<String> changedFields;
        if (previousSnapshot == null) {
            changedFields = List.of("initial");
        } else {
            AgentSnapshotDataDTO previousData = JsonUtils.parseObject(previousSnapshot.getSnapshotData(),
                    AgentSnapshotDataDTO.class);
            changedFields = getChangedFields(previousData, snapshotData);
        }
        if (changedFields.isEmpty()) {
            return;
        }

        insertSnapshot(agentId, agent.getUserId(), source, snapshotData, changedFields);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public PageData<AgentSnapshotVO> page(String agentId, AgentSnapshotPageDTO params) {
        AgentSnapshotPageDTO pageParams = params == null ? new AgentSnapshotPageDTO() : params;
        Page<AgentSnapshotEntity> page = new Page<>(pageParams.pageOrDefault(), pageParams.limitOrDefault());
        page.addOrder(OrderItem.desc("version_no"));
        IPage<AgentSnapshotEntity> result = agentSnapshotDao.selectPage(page,
                new QueryWrapper<AgentSnapshotEntity>()
                        .eq("agent_id", agentId)
                        .le(pageParams.getMaxVersionNo() != null, "version_no", pageParams.getMaxVersionNo()));
        List<AgentSnapshotVO> list = result.getRecords().stream()
                .map(entity -> toVO(entity, false))
                .toList();
        return new PageData<>(list, result.getTotal());
    }

    @Override
    public AgentSnapshotVO getSnapshot(String agentId, String snapshotId) {
        AgentSnapshotEntity entity = getSnapshotEntity(agentId, snapshotId);
        return toVO(entity, true);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void restoreSnapshot(String agentId, String snapshotId) {
        AgentEntity agent = agentDao.selectByIdForUpdate(agentId);
        if (agent == null) {
            throw new RenException(ErrorCode.AGENT_NOT_FOUND);
        }

        AgentSnapshotEntity snapshot = getSnapshotEntity(agentId, snapshotId);
        AgentSnapshotDataDTO data = JsonUtils.parseObject(snapshot.getSnapshotData(), AgentSnapshotDataDTO.class);
        if (data == null) {
            throw new RenException("快照数据为空，无法恢复");
        }

        AgentInfoVO currentAgent = getAgentInfo(agentId);
        AgentSnapshotDataDTO currentData = buildSnapshotData(currentAgent);
        AgentSnapshotDataDTO restoreData = preserveCurrentSensitiveValues(data, currentData);
        List<String> changedFields = getChangedFields(currentData, restoreData);
        if (changedFields.isEmpty()) {
            return;
        }

        applyAgentFields(agent, restoreData);
        validateRestoreParams(agent);
        applyMemoryPolicy(agent);
        agent.setUpdater(SecurityUser.getUserId());
        agent.setUpdatedAt(new Date());
        agentDao.updateById(agent);

        restoreFunctions(agentId, restoreData.getFunctions());
        restoreContextProviders(agentId, restoreData.getContextProviders());
        correctWordFileService.saveAgentCorrectWords(agentId, nullToEmpty(restoreData.getCorrectWordFileIds()));
        restoreTags(agentId, restoreData);
        insertSnapshot(agentId, currentAgent.getUserId(), "restore", restoreData, changedFields,
                snapshot.getId(), snapshot.getVersionNo());
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void deleteSnapshot(String agentId, String snapshotId) {
        AgentSnapshotEntity entity = getSnapshotEntity(agentId, snapshotId);
        Integer maxVersionNo = agentSnapshotDao.selectMaxVersionNo(agentId);
        if (Objects.equals(entity.getVersionNo(), maxVersionNo)) {
            throw new RenException("最新历史版本不能删除");
        }
        deleteById(snapshotId);
    }

    @Override
    public Integer getCurrentVersionNo(String agentId) {
        Integer maxVersionNo = agentSnapshotDao.selectMaxVersionNo(agentId);
        return maxVersionNo == null ? 0 : maxVersionNo;
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void deleteByAgentId(String agentId) {
        agentSnapshotDao.delete(new QueryWrapper<AgentSnapshotEntity>().eq("agent_id", agentId));
    }

    private void insertSnapshot(String agentId, Long userId, String source, AgentSnapshotDataDTO snapshotData,
            List<String> changedFields) {
        insertSnapshot(agentId, userId, source, snapshotData, changedFields, null, null);
    }

    private void insertSnapshot(String agentId, Long userId, String source, AgentSnapshotDataDTO snapshotData,
            List<String> changedFields, String restoreFromSnapshotId, Integer restoreFromVersionNo) {
        AgentSnapshotEntity entity = new AgentSnapshotEntity();
        entity.setId(UUID.randomUUID().toString().replace("-", ""));
        entity.setAgentId(agentId);
        entity.setUserId(userId);
        entity.setSnapshotData(JsonUtils.toJsonString(redactSnapshotData(snapshotData)));
        entity.setChangedFields(JsonUtils.toJsonString(changedFields));
        entity.setSource(StringUtils.defaultIfBlank(source, "config"));
        entity.setRestoreFromSnapshotId(restoreFromSnapshotId);
        entity.setRestoreFromVersionNo(restoreFromVersionNo);
        entity.setCreator(SecurityUser.getUserId());
        entity.setCreatedAt(new Date());
        int inserted = agentSnapshotDao.insertWithNextVersion(entity);
        if (inserted != 1) {
            throw new RenException("快照版本号生成失败");
        }
        pruneSnapshots(agentId);
    }

    private void lockAgent(String agentId) {
        if (agentDao.selectByIdForUpdate(agentId) == null) {
            throw new RenException(ErrorCode.AGENT_NOT_FOUND);
        }
    }

    private void pruneSnapshots(String agentId) {
        agentSnapshotDao.deleteOlderThanKeepLimit(agentId, MAX_SNAPSHOTS_PER_AGENT);
    }

    private AgentSnapshotEntity getSnapshotEntity(String agentId, String snapshotId) {
        AgentSnapshotEntity entity = selectById(snapshotId);
        if (entity == null || !Objects.equals(agentId, entity.getAgentId())) {
            throw new RenException("快照不存在");
        }
        return entity;
    }

    private AgentInfoVO getAgentInfo(String agentId) {
        AgentInfoVO agent = agentDao.selectAgentInfoById(agentId);
        if (agent == null) {
            throw new RenException(ErrorCode.AGENT_NOT_FOUND);
        }
        return agent;
    }

    private AgentSnapshotDataDTO buildSnapshotData(String agentId) {
        return buildSnapshotData(getAgentInfo(agentId));
    }

    private AgentSnapshotDataDTO buildSnapshotData(AgentInfoVO agent) {
        AgentSnapshotDataDTO data = new AgentSnapshotDataDTO();
        data.setAgentCode(agent.getAgentCode());
        data.setAgentName(agent.getAgentName());
        data.setAsrModelId(agent.getAsrModelId());
        data.setVadModelId(agent.getVadModelId());
        data.setLlmModelId(agent.getLlmModelId());
        data.setSlmModelId(agent.getSlmModelId());
        data.setVllmModelId(agent.getVllmModelId());
        data.setTtsModelId(agent.getTtsModelId());
        data.setTtsVoiceId(agent.getTtsVoiceId());
        data.setTtsLanguage(agent.getTtsLanguage());
        data.setTtsVolume(agent.getTtsVolume());
        data.setTtsRate(agent.getTtsRate());
        data.setTtsPitch(agent.getTtsPitch());
        data.setMemModelId(agent.getMemModelId());
        data.setIntentModelId(agent.getIntentModelId());
        data.setChatHistoryConf(agent.getChatHistoryConf());
        data.setSystemPrompt(agent.getSystemPrompt());
        data.setSummaryMemory(agent.getSummaryMemory());
        data.setLangCode(agent.getLangCode());
        data.setLanguage(agent.getLanguage());
        data.setSort(agent.getSort());
        data.setFunctions(toFunctionInfo(agent.getFunctions()));
        data.setContextProviders(getContextProviders(agent.getId()));
        data.setCorrectWordFileIds(nullToEmpty(correctWordFileService.getAgentCorrectWordFileIds(agent.getId())));
        List<AgentSnapshotTagDTO> tags = getSnapshotTags(agent.getId());
        data.setTags(tags);
        data.setTagNames(tags.stream().map(AgentSnapshotTagDTO::getTagName).toList());
        return data;
    }

    private List<AgentSnapshotTagDTO> getSnapshotTags(String agentId) {
        List<AgentTagEntity> tags = agentTagDao.selectByAgentId(agentId);
        if (tags == null || tags.isEmpty()) {
            return Collections.emptyList();
        }
        List<AgentSnapshotTagDTO> snapshotTags = new ArrayList<>();
        for (int i = 0; i < tags.size(); i++) {
            AgentTagEntity tag = tags.get(i);
            AgentSnapshotTagDTO snapshotTag = new AgentSnapshotTagDTO();
            snapshotTag.setId(tag.getId());
            snapshotTag.setTagName(tag.getTagName());
            snapshotTag.setSort(i);
            snapshotTags.add(snapshotTag);
        }
        return snapshotTags;
    }

    private List<AgentUpdateDTO.FunctionInfo> toFunctionInfo(List<AgentPluginMapping> mappings) {
        if (mappings == null || mappings.isEmpty()) {
            return Collections.emptyList();
        }
        return mappings.stream().map(mapping -> {
            AgentUpdateDTO.FunctionInfo info = new AgentUpdateDTO.FunctionInfo();
            info.setPluginId(mapping.getPluginId());
            info.setParamInfo(parseParamInfo(mapping.getParamInfo()));
            return info;
        }).toList();
    }

    private HashMap<String, Object> parseParamInfo(String paramInfo) {
        if (StringUtils.isBlank(paramInfo)) {
            return new HashMap<>();
        }
        return JsonUtils.parseObject(paramInfo, PARAM_INFO_TYPE);
    }

    private List<xiaozhi.modules.agent.dto.ContextProviderDTO> getContextProviders(String agentId) {
        AgentContextProviderEntity contextEntity = agentContextProviderService.getByAgentId(agentId);
        if (contextEntity == null || contextEntity.getContextProviders() == null) {
            return Collections.emptyList();
        }
        return contextEntity.getContextProviders();
    }

    private List<String> getChangedFields(AgentSnapshotDataDTO current, AgentUpdateDTO pendingUpdate) {
        if (pendingUpdate == null) {
            return List.of("restore");
        }

        List<String> fields = new ArrayList<>();
        for (AgentSnapshotField field : AgentSnapshotField.values()) {
            Object nextValue = field.updateValue(pendingUpdate);
            if (nextValue != null && isChanged(field, field.snapshotValue(current), nextValue)) {
                fields.add(field.getFieldName());
            }
        }
        return fields;
    }

    private List<String> getChangedFields(AgentSnapshotDataDTO current, AgentSnapshotDataDTO next) {
        if (next == null) {
            return List.of("restore");
        }
        if (current == null) {
            current = new AgentSnapshotDataDTO();
        }

        List<String> fields = new ArrayList<>();
        for (AgentSnapshotField field : AgentSnapshotField.values()) {
            if (isChanged(field, field.snapshotValue(current), field.snapshotValue(next))) {
                fields.add(field.getFieldName());
            }
        }
        return fields;
    }

    private boolean isChanged(AgentSnapshotField field, Object current, Object next) {
        return !Objects.equals(normalizeForCompare(field, current), normalizeForCompare(field, next));
    }

    @SuppressWarnings("unchecked")
    private Object normalizeForCompare(AgentSnapshotField field, Object value) {
        return switch (field) {
            case FUNCTIONS -> normalizeFunctions((List<AgentUpdateDTO.FunctionInfo>) value);
            case CONTEXT_PROVIDERS -> normalizeSortedJsonList((List<?>) value);
            case CORRECT_WORD_FILE_IDS -> normalizeStringList((List<String>) value);
            case TAG_NAMES -> normalizeStringList((List<String>) value);
            default -> value;
        };
    }

    private Map<String, Object> normalizeFunctions(List<AgentUpdateDTO.FunctionInfo> functions) {
        Map<String, Object> result = new TreeMap<>();
        if (functions == null) {
            return result;
        }
        for (AgentUpdateDTO.FunctionInfo function : functions) {
            if (function == null || StringUtils.isBlank(function.getPluginId())) {
                continue;
            }
            result.put(function.getPluginId(), normalizeMap(function.getParamInfo()));
        }
        return result;
    }

    private List<String> normalizeStringList(List<String> values) {
        if (values == null) {
            return Collections.emptyList();
        }
        return values.stream()
                .filter(StringUtils::isNotBlank)
                .sorted()
                .toList();
    }

    private <T> List<String> normalizeSortedJsonList(List<T> values) {
        if (values == null) {
            return Collections.emptyList();
        }
        return values.stream()
                .filter(Objects::nonNull)
                .map(value -> JsonUtils.toJsonString(normalizeValue(value)))
                .sorted()
                .toList();
    }

    private Object normalizeValue(Object value) {
        if (value == null) {
            return null;
        }
        if (value instanceof Map<?, ?> map) {
            return normalizeMap(map);
        }
        if (value instanceof List<?> list) {
            return list.stream().map(this::normalizeValue).toList();
        }
        if (isScalarValue(value)) {
            return value;
        }
        return normalizeMap(JsonUtils.parseObject(JsonUtils.toJsonString(value), OBJECT_MAP_TYPE));
    }

    private boolean isScalarValue(Object value) {
        return value instanceof CharSequence
                || value instanceof Number
                || value instanceof Boolean
                || value instanceof Character
                || value instanceof Enum<?>
                || value instanceof Date;
    }

    private Map<String, Object> normalizeMap(Map<?, ?> map) {
        Map<String, Object> result = new TreeMap<>();
        if (map == null) {
            return result;
        }
        map.forEach((key, value) -> {
            if (key != null) {
                String keyText = String.valueOf(key);
                result.put(keyText, isSensitiveKey(keyText) ? SECRET_PLACEHOLDER : normalizeValue(value));
            }
        });
        return result;
    }

    private void applyAgentFields(AgentEntity agent, AgentSnapshotDataDTO data) {
        for (AgentSnapshotField field : AgentSnapshotField.values()) {
            field.applyTo(agent, data);
        }
    }

    private void validateRestoreParams(AgentEntity agent) {
        if (agent == null || StringUtils.isBlank(agent.getLlmModelId())) {
            return;
        }

        ModelConfigEntity llmModelData = modelConfigService.selectById(agent.getLlmModelId());
        if (llmModelData == null || llmModelData.getConfigJson() == null) {
            throw new RenException(ErrorCode.LLM_INTENT_PARAMS_MISMATCH);
        }
        Object typeValue = llmModelData.getConfigJson().get("type");
        String type = typeValue == null ? "" : typeValue.toString();
        if ("openai".equals(type) || "ollama".equals(type)) {
            return;
        }
        if ("Intent_function_call".equals(agent.getIntentModelId())) {
            throw new RenException(ErrorCode.LLM_INTENT_PARAMS_MISMATCH);
        }
    }

    private void applyMemoryPolicy(AgentEntity agent) {
        if (agent == null || StringUtils.isBlank(agent.getMemModelId())) {
            return;
        }
        if (Constant.MEMORY_NO_MEM.equals(agent.getMemModelId())) {
            agentChatHistoryService.deleteByAgentId(agent.getId(), true, true);
            agent.setSummaryMemory("");
        } else if (Constant.MEMORY_MEM_REPORT_ONLY.equals(agent.getMemModelId())) {
            agent.setSummaryMemory("");
        }
    }

    private void restoreFunctions(String agentId, List<AgentUpdateDTO.FunctionInfo> functions) {
        agentPluginMappingService.deleteByAgentId(agentId);
        if (functions == null || functions.isEmpty()) {
            return;
        }
        List<AgentPluginMapping> mappings = functions.stream().map(info -> {
            AgentPluginMapping mapping = new AgentPluginMapping();
            mapping.setAgentId(agentId);
            mapping.setPluginId(info.getPluginId());
            mapping.setParamInfo(JsonUtils.toJsonString(info.getParamInfo()));
            return mapping;
        }).toList();
        agentPluginMappingService.saveBatch(mappings);
    }

    private void restoreContextProviders(String agentId,
            List<xiaozhi.modules.agent.dto.ContextProviderDTO> contextProviders) {
        AgentContextProviderEntity entity = new AgentContextProviderEntity();
        entity.setAgentId(agentId);
        entity.setContextProviders(nullToEmpty(contextProviders));
        entity.setUpdater(SecurityUser.getUserId());
        entity.setUpdatedAt(new Date());
        agentContextProviderService.saveOrUpdateByAgentId(entity);
    }

    private void restoreTags(String agentId, AgentSnapshotDataDTO data) {
        List<AgentSnapshotTagDTO> tags = data.getTags();
        if (tags == null || tags.isEmpty()) {
            agentTagService.saveAgentTags(agentId, null, nullToEmpty(data.getTagNames()));
            return;
        }

        agentTagRelationDao.deleteByAgentId(agentId);
        List<AgentTagRelationEntity> relations = new ArrayList<>();
        Date now = new Date();
        for (int i = 0; i < tags.size(); i++) {
            AgentSnapshotTagDTO snapshotTag = tags.get(i);
            String tagId = restoreTag(snapshotTag, now);
            if (StringUtils.isBlank(tagId)) {
                continue;
            }
            AgentTagRelationEntity relation = new AgentTagRelationEntity();
            relation.setId(UUID.randomUUID().toString().replace("-", ""));
            relation.setAgentId(agentId);
            relation.setTagId(tagId);
            relation.setSort(i);
            relation.setCreator(SecurityUser.getUserId());
            relation.setCreatedAt(now);
            relation.setUpdater(SecurityUser.getUserId());
            relation.setUpdatedAt(now);
            relations.add(relation);
        }
        if (!relations.isEmpty()) {
            agentTagRelationDao.batchInsertRelation(relations);
        }
    }

    private String restoreTag(AgentSnapshotTagDTO snapshotTag, Date now) {
        if (snapshotTag == null || StringUtils.isBlank(snapshotTag.getTagName())) {
            return null;
        }

        AgentTagEntity tag = null;
        if (StringUtils.isNotBlank(snapshotTag.getId())) {
            tag = agentTagDao.selectById(snapshotTag.getId());
            if (tag != null && Objects.equals(tag.getDeleted(), 1)) {
                tag = null;
            }
        }
        if (tag == null) {
            tag = agentTagDao.selectOne(new QueryWrapper<AgentTagEntity>()
                    .eq("tag_name", snapshotTag.getTagName())
                    .eq("deleted", 0)
                    .last("LIMIT 1"));
        }
        if (tag != null) {
            return tag.getId();
        }

        AgentTagEntity newTag = new AgentTagEntity();
        newTag.setId(UUID.randomUUID().toString().replace("-", ""));
        newTag.setTagName(snapshotTag.getTagName());
        newTag.setSort(snapshotTag.getSort() == null ? 0 : snapshotTag.getSort());
        newTag.setDeleted(0);
        newTag.setCreator(SecurityUser.getUserId());
        newTag.setCreatedAt(now);
        newTag.setUpdater(SecurityUser.getUserId());
        newTag.setUpdatedAt(now);
        agentTagDao.insert(newTag);
        return newTag.getId();
    }

    private AgentSnapshotVO toVO(AgentSnapshotEntity entity, boolean includeData) {
        AgentSnapshotVO vo = new AgentSnapshotVO();
        vo.setId(entity.getId());
        vo.setAgentId(entity.getAgentId());
        vo.setUserId(entity.getUserId());
        vo.setVersionNo(entity.getVersionNo());
        vo.setChangedFields(parseChangedFields(entity.getChangedFields()));
        vo.setFieldOrder(AgentSnapshotField.names());
        vo.setSource(entity.getSource());
        vo.setRestoreFromSnapshotId(entity.getRestoreFromSnapshotId());
        vo.setRestoreFromVersionNo(entity.getRestoreFromVersionNo());
        vo.setCreator(entity.getCreator());
        vo.setCreatedAt(entity.getCreatedAt());
        if (includeData) {
            vo.setSnapshotData(redactSnapshotData(JsonUtils.parseObject(entity.getSnapshotData(),
                    AgentSnapshotDataDTO.class)));
            vo.setAfterSnapshotData(redactSnapshotData(getAfterSnapshotData(entity)));
        }
        return vo;
    }

    private AgentSnapshotDataDTO getAfterSnapshotData(AgentSnapshotEntity entity) {
        AgentSnapshotEntity nextSnapshot = agentSnapshotDao.selectNextSnapshot(entity.getAgentId(), entity.getVersionNo());
        if (nextSnapshot != null) {
            return JsonUtils.parseObject(nextSnapshot.getSnapshotData(), AgentSnapshotDataDTO.class);
        }
        return null;
    }

    private List<String> parseChangedFields(String changedFields) {
        if (StringUtils.isBlank(changedFields)) {
            return Collections.emptyList();
        }
        return JsonUtils.parseObject(changedFields, STRING_LIST_TYPE);
    }

    private AgentSnapshotDataDTO redactSnapshotData(AgentSnapshotDataDTO data) {
        if (data == null) {
            return null;
        }
        AgentSnapshotDataDTO copy = JsonUtils.parseObject(JsonUtils.toJsonString(data), AgentSnapshotDataDTO.class);
        if (copy.getFunctions() != null) {
            copy.getFunctions().forEach(function -> {
                if (function != null) {
                    function.setParamInfo(redactSensitiveMap(function.getParamInfo()));
                }
            });
        }
        if (copy.getContextProviders() != null) {
            copy.getContextProviders().forEach(provider -> {
                if (provider != null) {
                    provider.setHeaders(redactSensitiveMap(provider.getHeaders()));
                }
            });
        }
        return copy;
    }

    private AgentSnapshotDataDTO preserveCurrentSensitiveValues(AgentSnapshotDataDTO target, AgentSnapshotDataDTO current) {
        if (target == null) {
            return null;
        }
        AgentSnapshotDataDTO copy = JsonUtils.parseObject(JsonUtils.toJsonString(target), AgentSnapshotDataDTO.class);
        Map<String, AgentUpdateDTO.FunctionInfo> currentFunctions = nullToEmpty(current == null ? null : current.getFunctions())
                .stream()
                .filter(function -> function != null && StringUtils.isNotBlank(function.getPluginId()))
                .collect(Collectors.toMap(AgentUpdateDTO.FunctionInfo::getPluginId, Function.identity(),
                        (left, right) -> left));
        if (copy.getFunctions() != null) {
            copy.getFunctions().forEach(function -> {
                if (function == null) {
                    return;
                }
                AgentUpdateDTO.FunctionInfo currentFunction = currentFunctions.get(function.getPluginId());
                function.setParamInfo(preserveCurrentSensitiveMap(function.getParamInfo(),
                        currentFunction == null ? null : currentFunction.getParamInfo()));
            });
        }

        Map<String, xiaozhi.modules.agent.dto.ContextProviderDTO> currentProviders = nullToEmpty(
                current == null ? null : current.getContextProviders())
                .stream()
                .filter(provider -> provider != null && StringUtils.isNotBlank(provider.getUrl()))
                .collect(Collectors.toMap(xiaozhi.modules.agent.dto.ContextProviderDTO::getUrl, Function.identity(),
                        (left, right) -> left));
        if (copy.getContextProviders() != null) {
            copy.getContextProviders().forEach(provider -> {
                if (provider == null) {
                    return;
                }
                xiaozhi.modules.agent.dto.ContextProviderDTO currentProvider = currentProviders.get(provider.getUrl());
                provider.setHeaders(preserveCurrentSensitiveMap(provider.getHeaders(),
                        currentProvider == null ? null : currentProvider.getHeaders()));
            });
        }
        return copy;
    }

    private HashMap<String, Object> redactSensitiveMap(Map<?, ?> map) {
        HashMap<String, Object> result = new HashMap<>();
        if (map == null) {
            return result;
        }
        map.forEach((key, value) -> {
            if (key != null) {
                String keyText = String.valueOf(key);
                result.put(keyText, isSensitiveKey(keyText) ? SECRET_PLACEHOLDER : redactSensitiveValue(value));
            }
        });
        return result;
    }

    private Object redactSensitiveValue(Object value) {
        if (value instanceof Map<?, ?> map) {
            return redactSensitiveMap(map);
        }
        if (value instanceof List<?> list) {
            return list.stream().map(this::redactSensitiveValue).toList();
        }
        return value;
    }

    private HashMap<String, Object> preserveCurrentSensitiveMap(Map<?, ?> target, Map<?, ?> current) {
        HashMap<String, Object> result = new HashMap<>();
        if (target == null) {
            return result;
        }
        target.forEach((key, value) -> {
            if (key == null) {
                return;
            }
            String keyText = String.valueOf(key);
            Object currentValue = getMapValue(current, keyText);
            if (isSensitiveKey(keyText)) {
                result.put(keyText, currentValue == null || SECRET_PLACEHOLDER.equals(currentValue) ? "" : currentValue);
            } else {
                result.put(keyText, preserveCurrentSensitiveValue(value, currentValue));
            }
        });
        return result;
    }

    private Object preserveCurrentSensitiveValue(Object target, Object current) {
        if (target instanceof Map<?, ?> targetMap) {
            return preserveCurrentSensitiveMap(targetMap, current instanceof Map<?, ?> currentMap ? currentMap : null);
        }
        if (target instanceof List<?> targetList) {
            List<?> currentList = current instanceof List<?> list ? list : Collections.emptyList();
            List<Object> result = new ArrayList<>();
            for (int i = 0; i < targetList.size(); i++) {
                Object currentItem = i < currentList.size() ? currentList.get(i) : null;
                result.add(preserveCurrentSensitiveValue(targetList.get(i), currentItem));
            }
            return result;
        }
        return target;
    }

    private Object getMapValue(Map<?, ?> map, String key) {
        if (map == null) {
            return null;
        }
        if (map.containsKey(key)) {
            return map.get(key);
        }
        for (Map.Entry<?, ?> entry : map.entrySet()) {
            if (entry.getKey() != null && Objects.equals(key, String.valueOf(entry.getKey()))) {
                return entry.getValue();
            }
        }
        return null;
    }

    private boolean isSensitiveKey(String key) {
        String normalized = StringUtils.defaultString(key).toLowerCase().replaceAll("[^a-z0-9]", "");
        return normalized.equals("authorization")
                || normalized.equals("token")
                || normalized.endsWith("token")
                || normalized.contains("apikey")
                || normalized.contains("appkey")
                || normalized.contains("accesskey")
                || normalized.contains("privatekey")
                || normalized.contains("password")
                || normalized.contains("passwd")
                || normalized.contains("secret")
                || normalized.contains("credential");
    }

    private <T> List<T> nullToEmpty(List<T> list) {
        return list == null ? Collections.emptyList() : list;
    }
}
