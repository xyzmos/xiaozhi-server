package xiaozhi.modules.agent.service.impl;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

import org.apache.commons.lang3.StringUtils;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
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
import xiaozhi.modules.agent.dto.AgentSnapshotTagDTO;
import xiaozhi.modules.agent.dto.AgentUpdateDTO;
import xiaozhi.modules.agent.entity.AgentContextProviderEntity;
import xiaozhi.modules.agent.entity.AgentEntity;
import xiaozhi.modules.agent.entity.AgentPluginMapping;
import xiaozhi.modules.agent.entity.AgentSnapshotEntity;
import xiaozhi.modules.agent.entity.AgentTagEntity;
import xiaozhi.modules.agent.entity.AgentTagRelationEntity;
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
    private static final TypeReference<List<String>> STRING_LIST_TYPE = new TypeReference<>() {
    };
    private static final TypeReference<HashMap<String, Object>> PARAM_INFO_TYPE = new TypeReference<>() {
    };

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
    public void createSnapshot(String agentId, String source, AgentUpdateDTO pendingUpdate) {
        AgentSnapshotDataDTO snapshotData = buildSnapshotData(agentId);
        List<String> changedFields = getChangedFields(snapshotData, pendingUpdate);
        if (pendingUpdate != null && changedFields.isEmpty()) {
            return;
        }

        AgentInfoVO agent = agentDao.selectAgentInfoById(agentId);
        if (agent == null) {
            throw new RenException(ErrorCode.AGENT_NOT_FOUND);
        }

        AgentSnapshotEntity entity = new AgentSnapshotEntity();
        entity.setAgentId(agentId);
        entity.setUserId(agent.getUserId());
        entity.setSnapshotData(JsonUtils.toJsonString(snapshotData));
        entity.setChangedFields(JsonUtils.toJsonString(changedFields));
        entity.setSource(StringUtils.defaultIfBlank(source, "config"));
        entity.setCreator(SecurityUser.getUserId());
        entity.setCreatedAt(new Date());
        insertSnapshotWithRetry(entity);
    }

    @Override
    public PageData<AgentSnapshotVO> page(String agentId, Map<String, Object> params) {
        IPage<AgentSnapshotEntity> page = getPage(params, "created_at", false);
        IPage<AgentSnapshotEntity> result = agentSnapshotDao.selectPage(page,
                new QueryWrapper<AgentSnapshotEntity>().eq("agent_id", agentId));
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
        AgentSnapshotEntity snapshot = getSnapshotEntity(agentId, snapshotId);
        AgentSnapshotDataDTO data = JsonUtils.parseObject(snapshot.getSnapshotData(), AgentSnapshotDataDTO.class);
        if (data == null) {
            throw new RenException("快照数据为空，无法恢复");
        }

        createSnapshot(agentId, "restore", null);

        AgentEntity agent = agentDao.selectById(agentId);
        if (agent == null) {
            throw new RenException(ErrorCode.AGENT_NOT_FOUND);
        }
        applyAgentFields(agent, data);
        validateRestoreParams(agent);
        applyMemoryPolicy(agent);
        agent.setUpdater(SecurityUser.getUserId());
        agent.setUpdatedAt(new Date());
        agentDao.updateById(agent);

        restoreFunctions(agentId, data.getFunctions());
        restoreContextProviders(agentId, data.getContextProviders());
        correctWordFileService.saveAgentCorrectWords(agentId, nullToEmpty(data.getCorrectWordFileIds()));
        restoreTags(agentId, data);
    }

    private void insertSnapshotWithRetry(AgentSnapshotEntity entity) {
        for (int attempt = 0; attempt < 3; attempt++) {
            Integer maxVersionNo = agentSnapshotDao.selectMaxVersionNo(entity.getAgentId());
            entity.setVersionNo((maxVersionNo == null ? 0 : maxVersionNo) + 1);
            try {
                agentSnapshotDao.insert(entity);
                return;
            } catch (DuplicateKeyException e) {
                if (attempt == 2) {
                    throw e;
                }
            }
        }
    }

    private AgentSnapshotEntity getSnapshotEntity(String agentId, String snapshotId) {
        AgentSnapshotEntity entity = selectById(snapshotId);
        if (entity == null || !Objects.equals(agentId, entity.getAgentId())) {
            throw new RenException("快照不存在");
        }
        return entity;
    }

    private AgentSnapshotDataDTO buildSnapshotData(String agentId) {
        AgentInfoVO agent = agentDao.selectAgentInfoById(agentId);
        if (agent == null) {
            throw new RenException(ErrorCode.AGENT_NOT_FOUND);
        }

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
        data.setContextProviders(getContextProviders(agentId));
        data.setCorrectWordFileIds(nullToEmpty(correctWordFileService.getAgentCorrectWordFileIds(agentId)));
        List<AgentSnapshotTagDTO> tags = getSnapshotTags(agentId);
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
        compare(fields, "agentCode", current.getAgentCode(), pendingUpdate.getAgentCode());
        compare(fields, "agentName", current.getAgentName(), pendingUpdate.getAgentName());
        compare(fields, "asrModelId", current.getAsrModelId(), pendingUpdate.getAsrModelId());
        compare(fields, "vadModelId", current.getVadModelId(), pendingUpdate.getVadModelId());
        compare(fields, "llmModelId", current.getLlmModelId(), pendingUpdate.getLlmModelId());
        compare(fields, "slmModelId", current.getSlmModelId(), pendingUpdate.getSlmModelId());
        compare(fields, "vllmModelId", current.getVllmModelId(), pendingUpdate.getVllmModelId());
        compare(fields, "ttsModelId", current.getTtsModelId(), pendingUpdate.getTtsModelId());
        compare(fields, "ttsVoiceId", current.getTtsVoiceId(), pendingUpdate.getTtsVoiceId());
        compare(fields, "ttsLanguage", current.getTtsLanguage(), pendingUpdate.getTtsLanguage());
        compare(fields, "ttsVolume", current.getTtsVolume(), pendingUpdate.getTtsVolume());
        compare(fields, "ttsRate", current.getTtsRate(), pendingUpdate.getTtsRate());
        compare(fields, "ttsPitch", current.getTtsPitch(), pendingUpdate.getTtsPitch());
        compare(fields, "memModelId", current.getMemModelId(), pendingUpdate.getMemModelId());
        compare(fields, "intentModelId", current.getIntentModelId(), pendingUpdate.getIntentModelId());
        compare(fields, "chatHistoryConf", current.getChatHistoryConf(), pendingUpdate.getChatHistoryConf());
        compare(fields, "systemPrompt", current.getSystemPrompt(), pendingUpdate.getSystemPrompt());
        compare(fields, "summaryMemory", current.getSummaryMemory(), pendingUpdate.getSummaryMemory());
        compare(fields, "langCode", current.getLangCode(), pendingUpdate.getLangCode());
        compare(fields, "language", current.getLanguage(), pendingUpdate.getLanguage());
        compare(fields, "sort", current.getSort(), pendingUpdate.getSort());
        compare(fields, "functions", current.getFunctions(), pendingUpdate.getFunctions());
        compare(fields, "contextProviders", current.getContextProviders(), pendingUpdate.getContextProviders());
        compare(fields, "correctWordFileIds", current.getCorrectWordFileIds(), pendingUpdate.getCorrectWordFileIds());
        compare(fields, "tagNames", current.getTagNames(), pendingUpdate.getTagNames());
        compare(fields, "tagIds", current.getTags().stream().map(AgentSnapshotTagDTO::getId).toList(),
                pendingUpdate.getTagIds());
        return fields;
    }

    private <T> void compare(List<String> fields, String name, T current, T next) {
        if (next != null && !Objects.equals(current, next)) {
            fields.add(name);
        }
    }

    private void applyAgentFields(AgentEntity agent, AgentSnapshotDataDTO data) {
        agent.setAgentCode(data.getAgentCode());
        agent.setAgentName(data.getAgentName());
        agent.setAsrModelId(data.getAsrModelId());
        agent.setVadModelId(data.getVadModelId());
        agent.setLlmModelId(data.getLlmModelId());
        agent.setSlmModelId(data.getSlmModelId());
        agent.setVllmModelId(data.getVllmModelId());
        agent.setTtsModelId(data.getTtsModelId());
        agent.setTtsVoiceId(data.getTtsVoiceId());
        agent.setTtsLanguage(data.getTtsLanguage());
        agent.setTtsVolume(data.getTtsVolume());
        agent.setTtsRate(data.getTtsRate());
        agent.setTtsPitch(data.getTtsPitch());
        agent.setMemModelId(data.getMemModelId());
        agent.setIntentModelId(data.getIntentModelId());
        agent.setChatHistoryConf(data.getChatHistoryConf());
        agent.setSystemPrompt(data.getSystemPrompt());
        agent.setSummaryMemory(data.getSummaryMemory());
        agent.setLangCode(data.getLangCode());
        agent.setLanguage(data.getLanguage());
        agent.setSort(data.getSort());
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
        }
        if (tag == null) {
            tag = agentTagDao.selectOne(new QueryWrapper<AgentTagEntity>()
                    .eq("tag_name", snapshotTag.getTagName())
                    .last("LIMIT 1"));
        }
        if (tag != null) {
            if (Objects.equals(tag.getDeleted(), 1)) {
                tag.setDeleted(0);
                tag.setUpdater(SecurityUser.getUserId());
                tag.setUpdatedAt(now);
                agentTagDao.updateById(tag);
            }
            return tag.getId();
        }

        AgentTagEntity newTag = new AgentTagEntity();
        if (StringUtils.isNotBlank(snapshotTag.getId())) {
            newTag.setId(snapshotTag.getId());
        }
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
        vo.setSource(entity.getSource());
        vo.setCreator(entity.getCreator());
        vo.setCreatedAt(entity.getCreatedAt());
        if (includeData) {
            vo.setSnapshotData(JsonUtils.parseObject(entity.getSnapshotData(), AgentSnapshotDataDTO.class));
            vo.setAfterSnapshotData(getAfterSnapshotData(entity));
        }
        return vo;
    }

    private AgentSnapshotDataDTO getAfterSnapshotData(AgentSnapshotEntity entity) {
        AgentSnapshotEntity nextSnapshot = agentSnapshotDao.selectNextSnapshot(entity.getAgentId(), entity.getVersionNo());
        if (nextSnapshot != null) {
            return JsonUtils.parseObject(nextSnapshot.getSnapshotData(), AgentSnapshotDataDTO.class);
        }
        return buildSnapshotData(entity.getAgentId());
    }

    private List<String> parseChangedFields(String changedFields) {
        if (StringUtils.isBlank(changedFields)) {
            return Collections.emptyList();
        }
        return JsonUtils.parseObject(changedFields, STRING_LIST_TYPE);
    }

    private <T> List<T> nullToEmpty(List<T> list) {
        return list == null ? Collections.emptyList() : list;
    }
}
