<template>
  <div>
    <el-dialog
      :title="$t('agentSnapshot.title')"
      :visible="visible"
      width="760px"
      class="agent-snapshot-dialog"
      @open="open"
      @close="close"
    >
      <el-table
        v-loading="loading"
        :data="snapshots"
        :row-key="snapshotRowKey"
        :row-class-name="snapshotRowClassName"
        size="small"
        class="snapshot-table"
        :empty-text="loading ? ' ' : $t('agentSnapshot.empty')"
      >
        <el-table-column
          prop="versionNo"
          :label="$t('agentSnapshot.version')"
          width="90"
        >
          <template slot-scope="scope">
            <div class="version-cell">
              <span>#{{ scope.row.versionNo }}</span>
              <span
                v-if="scope.row.isCurrentVersion"
                class="latest-version-icon"
                :title="$t('agentSnapshot.currentVersion')"
              ></span>
            </div>
          </template>
        </el-table-column>
        <el-table-column
          prop="createdAt"
          :label="$t('agentSnapshot.createdAt')"
          width="170"
        >
          <template slot-scope="scope">
            {{ formatTime(scope.row.createdAt) || "—" }}
          </template>
        </el-table-column>
        <el-table-column
          prop="source"
          :label="$t('agentSnapshot.source')"
          width="110"
        >
          <template slot-scope="scope">
            {{ sourceLabel(scope.row.source) }}
          </template>
        </el-table-column>
        <el-table-column :label="$t('agentSnapshot.changedFields')" min-width="220">
          <template slot-scope="scope">
            <div v-if="(scope.row.changedFields || []).length" class="field-tags">
              <el-tag
                v-for="field in scope.row.changedFields"
                :key="field"
                size="mini"
                effect="plain"
              >
                {{ fieldLabel(field) }}
              </el-tag>
            </div>
            <span v-else class="field-tags-empty">—</span>
          </template>
        </el-table-column>
        <el-table-column :label="$t('agentSnapshot.actions')" width="190" fixed="right">
          <template slot-scope="scope">
            <el-button
              v-if="canViewSnapshot(scope.row)"
              type="text"
              size="small"
              @click="viewSnapshot(scope.row)"
            >
              {{ $t('agentSnapshot.view') }}
            </el-button>
            <el-button
              v-if="canRestoreSnapshot(scope.row)"
              type="text"
              size="small"
              @click="restoreSnapshot(scope.row)"
            >
              {{ $t('agentSnapshot.restore') }}
            </el-button>
            <el-button
              v-if="canDeleteSnapshot(scope.row)"
              type="text"
              size="small"
              class="snapshot-delete-button"
              :loading="deletingSnapshotId === scope.row.id"
              @click="deleteSnapshot(scope.row)"
            >
              {{ $t('agentSnapshot.delete') }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-row">
        <el-pagination
          :current-page="page"
          :page-size="limit"
          :total="total"
          layout="prev, pager, next, total"
          small
          @current-change="handlePageChange"
        />
      </div>
    </el-dialog>

    <el-dialog
      :title="detailDialogTitle"
      :visible.sync="detailVisible"
      width="860px"
      class="snapshot-detail-dialog"
    >
      <div v-loading="detailLoading" class="snapshot-diff">
        <template v-if="currentSnapshot && snapshotDiffs.length">
          <div class="detail-summary">
            <span>#{{ currentSnapshot.versionNo }}</span>
            <span>{{ formatTime(currentSnapshot.createdAt) }}</span>
            <span>{{ sourceLabel(currentSnapshot.source) }}</span>
          </div>

          <div
            v-for="item in snapshotDiffs"
            :key="item.field"
            class="diff-item"
          >
            <div class="diff-field">{{ item.label }}</div>
            <div v-if="item.displayType === 'functions'" class="function-change-view">
              <div v-if="item.functionChanges.length" class="function-toggle-list">
                <div
                  v-for="(change, changeIndex) in item.functionChanges"
                  :key="`function-change-${item.field}-${change.pluginId}-${changeIndex}`"
                  class="function-toggle-card"
                  :class="`is-${change.type}`"
                >
                  <div class="function-toggle-head">
                    <span class="function-dot"></span>
                    <div class="function-change-title-wrap">
                      <div class="function-change-title-row">
                        <span class="function-change-name">{{ change.name }}</span>
                        <span class="function-change-badge">{{ change.badge }}</span>
                      </div>
                    </div>
                  </div>

                  <div class="function-state-grid">
                    <div
                      class="function-state-pane is-before"
                      :class="{ 'is-enabled': change.before.active, 'is-disabled': !change.before.active }"
                    >
                      <div class="function-state-title">
                        <span>{{ item.beforeTitle }}</span>
                        <span class="function-state-badge">{{ change.before.status }}</span>
                      </div>
                      <div v-if="change.before.active && change.before.params.length" class="function-state-params">
                        <div
                          v-for="param in change.before.params"
                          :key="`${change.pluginId}-before-${param.key}`"
                          class="function-param-row"
                          :class="{ 'is-changed': param.changed }"
                        >
                          <span class="param-key">{{ param.label }}</span>
                          <span class="param-value">{{ param.value }}</span>
                        </div>
                      </div>
                      <div v-else class="function-state-empty">{{ change.before.note }}</div>
                    </div>

                    <div
                      class="function-state-pane is-after"
                      :class="{ 'is-enabled': change.after.active, 'is-disabled': !change.after.active }"
                    >
                      <div class="function-state-title">
                        <span>{{ item.afterTitle }}</span>
                        <span class="function-state-badge">{{ change.after.status }}</span>
                      </div>
                      <div v-if="change.after.active && change.after.params.length" class="function-state-params">
                        <div
                          v-for="param in change.after.params"
                          :key="`${change.pluginId}-after-${param.key}`"
                          class="function-param-row"
                          :class="{ 'is-changed': param.changed }"
                        >
                          <span class="param-key">{{ param.label }}</span>
                          <span class="param-value">{{ param.value }}</span>
                        </div>
                      </div>
                      <div v-else class="function-state-empty">{{ change.after.note }}</div>
                    </div>
                  </div>
                </div>
              </div>
              <div v-else class="value-empty">{{ $t('agentSnapshot.noFunctionChange') }}</div>
            </div>
            <div v-else class="diff-values" :class="{ 'is-complex': item.complex }">
              <div class="diff-pane diff-before">
                <div class="diff-pane-title">{{ item.beforeTitle }}</div>
                <div class="diff-value" :class="valueClass(item)">
                  <div
                    v-if="item.displayType === 'markdown'"
                    class="markdown-body"
                    v-html="renderMarkdownValue(item.beforeValue)"
                  ></div>
                  <pre v-else class="diff-text">{{ item.beforeText }}</pre>
                </div>
              </div>
              <div class="diff-pane diff-after">
                <div class="diff-pane-title">{{ item.afterTitle }}</div>
                <div class="diff-value" :class="valueClass(item)">
                  <div
                    v-if="item.displayType === 'markdown'"
                    class="markdown-body"
                    v-html="renderMarkdownValue(item.afterValue)"
                  ></div>
                  <pre v-else class="diff-text">{{ item.afterText }}</pre>
                </div>
              </div>
            </div>
          </div>
        </template>
        <el-empty
          v-else-if="!detailLoading"
          :description="$t('agentSnapshot.noChangedContent')"
          :image-size="80"
        />
      </div>
    </el-dialog>

    <el-dialog
      :title="restorePreviewTitle"
      :visible.sync="restorePreviewVisible"
      width="860px"
      class="snapshot-detail-dialog"
    >
      <div v-loading="restorePreviewLoading" class="snapshot-diff">
        <template v-if="restorePreviewSnapshot && restorePreviewDiffs.length">
          <div class="detail-summary">
            <span>#{{ restorePreviewSnapshot.versionNo }}</span>
            <span>{{ formatTime(restorePreviewSnapshot.createdAt) }}</span>
            <span>{{ sourceLabel(restorePreviewSnapshot.source) }}</span>
          </div>

          <div
            v-for="item in restorePreviewDiffs"
            :key="item.field"
            class="diff-item"
          >
            <div class="diff-field">{{ item.label }}</div>
            <div v-if="item.displayType === 'functions'" class="function-change-view">
              <div v-if="item.functionChanges.length" class="function-toggle-list">
                <div
                  v-for="(change, changeIndex) in item.functionChanges"
                  :key="`restore-function-change-${item.field}-${change.pluginId}-${changeIndex}`"
                  class="function-toggle-card"
                  :class="`is-${change.type}`"
                >
                  <div class="function-toggle-head">
                    <span class="function-dot"></span>
                    <div class="function-change-title-wrap">
                      <div class="function-change-title-row">
                        <span class="function-change-name">{{ change.name }}</span>
                        <span class="function-change-badge">{{ change.badge }}</span>
                      </div>
                    </div>
                  </div>

                  <div class="function-state-grid">
                    <div
                      class="function-state-pane is-before"
                      :class="{ 'is-enabled': change.before.active, 'is-disabled': !change.before.active }"
                    >
                      <div class="function-state-title">
                        <span>{{ item.beforeTitle }}</span>
                        <span class="function-state-badge">{{ change.before.status }}</span>
                      </div>
                      <div v-if="change.before.active && change.before.params.length" class="function-state-params">
                        <div
                          v-for="param in change.before.params"
                          :key="`${change.pluginId}-restore-before-${param.key}`"
                          class="function-param-row"
                          :class="{ 'is-changed': param.changed }"
                        >
                          <span class="param-key">{{ param.label }}</span>
                          <span class="param-value">{{ param.value }}</span>
                        </div>
                      </div>
                      <div v-else class="function-state-empty">{{ change.before.note }}</div>
                    </div>

                    <div
                      class="function-state-pane is-after"
                      :class="{ 'is-enabled': change.after.active, 'is-disabled': !change.after.active }"
                    >
                      <div class="function-state-title">
                        <span>{{ item.afterTitle }}</span>
                        <span class="function-state-badge">{{ change.after.status }}</span>
                      </div>
                      <div v-if="change.after.active && change.after.params.length" class="function-state-params">
                        <div
                          v-for="param in change.after.params"
                          :key="`${change.pluginId}-restore-after-${param.key}`"
                          class="function-param-row"
                          :class="{ 'is-changed': param.changed }"
                        >
                          <span class="param-key">{{ param.label }}</span>
                          <span class="param-value">{{ param.value }}</span>
                        </div>
                      </div>
                      <div v-else class="function-state-empty">{{ change.after.note }}</div>
                    </div>
                  </div>
                </div>
              </div>
              <div v-else class="value-empty">{{ $t('agentSnapshot.noFunctionChange') }}</div>
            </div>
            <div v-else class="diff-values" :class="{ 'is-complex': item.complex }">
              <div class="diff-pane diff-before">
                <div class="diff-pane-title">{{ item.beforeTitle }}</div>
                <div class="diff-value" :class="valueClass(item)">
                  <div
                    v-if="item.displayType === 'markdown'"
                    class="markdown-body"
                    v-html="renderMarkdownValue(item.beforeValue)"
                  ></div>
                  <pre v-else class="diff-text">{{ item.beforeText }}</pre>
                </div>
              </div>
              <div class="diff-pane diff-after">
                <div class="diff-pane-title">{{ item.afterTitle }}</div>
                <div class="diff-value" :class="valueClass(item)">
                  <div
                    v-if="item.displayType === 'markdown'"
                    class="markdown-body"
                    v-html="renderMarkdownValue(item.afterValue)"
                  ></div>
                  <pre v-else class="diff-text">{{ item.afterText }}</pre>
                </div>
              </div>
            </div>
          </div>
        </template>
        <el-empty
          v-else-if="!restorePreviewLoading"
          :description="$t('agentSnapshot.noChangedContent')"
          :image-size="80"
        />
        <el-alert
          v-if="restorePreviewSnapshot"
          class="restore-risk-alert"
          type="info"
          :closable="false"
          show-icon
          :title="$t('agentSnapshot.restoreConfirm', { version: restoreTargetVersion })"
        />
        <el-alert
          v-if="restoreWillClearChatHistory"
          class="restore-risk-alert"
          type="warning"
          :closable="false"
          show-icon
          :title="$t('agentSnapshot.restoreMemoryWarning')"
        />
      </div>
      <span slot="footer" class="dialog-footer">
        <el-button @click="restorePreviewVisible = false">
          {{ $t('button.cancel') }}
        </el-button>
        <el-button
          type="primary"
          :loading="restoring"
          :disabled="restorePreviewLoading || !restorePreviewSnapshot || restorePreviewDiffs.length === 0"
          @click="confirmRestoreSnapshot"
        >
          {{ $t('agentSnapshot.confirmRestore') }}
        </el-button>
      </span>
    </el-dialog>
  </div>
</template>

<script>
import Api from "@/apis/api";
import { formatDate } from "@/utils/date";

const FALLBACK_PLUGIN_NAME_KEYS = {
  SYSTEM_PLUGIN_WEATHER: "agentSnapshot.plugin.SYSTEM_PLUGIN_WEATHER",
  SYSTEM_PLUGIN_MUSIC: "agentSnapshot.plugin.SYSTEM_PLUGIN_MUSIC",
  SYSTEM_PLUGIN_NEWS_CHINANEWS: "agentSnapshot.plugin.SYSTEM_PLUGIN_NEWS_CHINANEWS",
  SYSTEM_PLUGIN_NEWS_NEWSNOW: "agentSnapshot.plugin.SYSTEM_PLUGIN_NEWS_NEWSNOW",
  SYSTEM_PLUGIN_HA_GET_STATE: "agentSnapshot.plugin.SYSTEM_PLUGIN_HA_GET_STATE",
  SYSTEM_PLUGIN_HA_SET_STATE: "agentSnapshot.plugin.SYSTEM_PLUGIN_HA_SET_STATE",
  SYSTEM_PLUGIN_HA_PLAY_MUSIC: "agentSnapshot.plugin.SYSTEM_PLUGIN_HA_PLAY_MUSIC",
  SYSTEM_PLUGIN_WEB_SEARCH: "agentSnapshot.plugin.SYSTEM_PLUGIN_WEB_SEARCH",
  SYSTEM_PLUGIN_CALL_DEVICE: "agentSnapshot.plugin.SYSTEM_PLUGIN_CALL_DEVICE"
};

const FALLBACK_FIELD_LABEL_KEYS = {
  url: "agentSnapshot.pluginField.url",
  news_sources: "agentSnapshot.pluginField.news_sources",
  default_rss_url: "agentSnapshot.pluginField.default_rss_url",
  society_rss_url: "agentSnapshot.pluginField.society_rss_url",
  world_rss_url: "agentSnapshot.pluginField.world_rss_url",
  finance_rss_url: "agentSnapshot.pluginField.finance_rss_url",
  api_key: "agentSnapshot.pluginField.api_key",
  default_location: "agentSnapshot.pluginField.default_location",
  api_host: "agentSnapshot.pluginField.api_host",
  base_url: "agentSnapshot.pluginField.base_url",
  devices: "agentSnapshot.pluginField.devices",
  provider: "agentSnapshot.pluginField.provider",
  description: "agentSnapshot.pluginField.description",
  max_results: "agentSnapshot.pluginField.max_results"
};

const MODEL_FIELD_TYPES = {
  asrModelId: "ASR",
  vadModelId: "VAD",
  llmModelId: "LLM",
  slmModelId: "SLM",
  vllmModelId: "VLLM",
  ttsModelId: "TTS",
  memModelId: "Memory",
  intentModelId: "Intent"
};

const MODEL_TYPES = ["ASR", "VAD", "LLM", "SLM", "VLLM", "TTS", "Memory", "Intent"];

const FALLBACK_MODEL_NAME_KEYS = {
  Memory_nomem: "agentSnapshot.model.Memory_nomem",
  Memory_mem_local_short: "agentSnapshot.model.Memory_mem_local_short",
  Memory_mem0ai: "agentSnapshot.model.Memory_mem0ai",
  Memory_mem_report_only: "agentSnapshot.model.Memory_mem_report_only",
  Intent_nointent: "agentSnapshot.model.Intent_nointent",
  Intent_intent_llm: "agentSnapshot.model.Intent_intent_llm",
  Intent_function_call: "agentSnapshot.model.Intent_function_call"
};

const FALLBACK_VOICE_NAME_KEYS = {
  TTS_EdgeTTS0001: "agentSnapshot.voice.TTS_EdgeTTS0001",
  TTS_EdgeTTS0002: "agentSnapshot.voice.TTS_EdgeTTS0002",
  TTS_EdgeTTS0003: "agentSnapshot.voice.TTS_EdgeTTS0003",
  TTS_EdgeTTS0004: "agentSnapshot.voice.TTS_EdgeTTS0004",
  TTS_EdgeTTS0005: "agentSnapshot.voice.TTS_EdgeTTS0005",
  TTS_EdgeTTS0006: "agentSnapshot.voice.TTS_EdgeTTS0006"
};

const CHAT_HISTORY_CONF_LABEL_KEYS = {
  0: "agentSnapshot.chatHistoryConf.none",
  1: "agentSnapshot.chatHistoryConf.text",
  2: "agentSnapshot.chatHistoryConf.textVoice"
};

export default {
  name: "AgentSnapshotDialog",
  props: {
    visible: {
      type: Boolean,
      default: false
    },
    agentId: {
      type: String,
      required: true
    },
    currentVersionNo: {
      type: Number,
      default: null
    }
  },
  data() {
    return {
      loading: false,
      detailLoading: false,
      detailVisible: false,
      restorePreviewLoading: false,
      restorePreviewVisible: false,
      restoring: false,
      snapshots: [],
      currentSnapshot: null,
      restorePreviewSnapshot: null,
      restorePreviewRow: null,
      deletingSnapshotId: null,
      pluginMetadata: {},
      pluginMetadataLoaded: false,
      pluginMetadataLoading: null,
      modelNameMap: {},
      modelMetadataLoaded: false,
      modelMetadataLoading: null,
      voiceNameMap: {},
      voiceMetadataLoading: {},
      loadedVoiceModelIds: {},
      snapshotFetchSeq: 0,
      detailFetchSeq: 0,
      restorePreviewFetchSeq: 0,
      restoreActionSeq: 0,
      deleteActionSeq: 0,
      historyAnchorVersionNo: null,
      historyTotal: 0,
      page: 1,
      limit: 10,
      total: 0
    };
  },
  computed: {
    detailDialogTitle() {
      if (!this.currentSnapshot) {
        return this.$t("agentSnapshot.detailTitle");
      }
      return this.formatVersionRangeTitle(
        this.$t("agentSnapshot.detailTitle"),
        this.currentSnapshot.beforeVersionNo,
        this.currentSnapshot.afterVersionNo || this.currentSnapshot.versionNo
      );
    },
    restorePreviewTitle() {
      if (!this.restorePreviewSnapshot) {
        return this.$t("agentSnapshot.restorePreviewTitle");
      }
      const beforeVersionNo = this.restorePreviewSnapshot.beforeVersionNo || this.resolveCurrentVersionNo();
      const afterVersionNo = this.restorePreviewSnapshot.afterVersionNo || this.restorePreviewSnapshot.versionNo;
      return this.formatVersionRangeTitle(
        this.$t("agentSnapshot.restorePreviewTitle"),
        beforeVersionNo,
        afterVersionNo
      );
    },
    snapshotDiffs() {
      if (!this.currentSnapshot || !this.hasAfterSnapshotData(this.currentSnapshot)) {
        return [];
      }

      const beforeData = this.currentSnapshot.snapshotData || {};
      const afterData = this.currentSnapshot.afterSnapshotData || {};
      return this.buildDiffs(beforeData, afterData, this.currentSnapshot.changedFields || [], {
        beforeLabel: this.$t("agentSnapshot.beforeChange"),
        afterLabel: this.$t("agentSnapshot.afterChange"),
        beforeVersionNo: this.currentSnapshot.beforeVersionNo,
        afterVersionNo: this.currentSnapshot.afterVersionNo || this.currentSnapshot.versionNo,
        fieldOrder: this.currentSnapshot.fieldOrder
      });
    },
    restorePreviewDiffs() {
      if (!this.restorePreviewSnapshot) {
        return [];
      }

      return this.buildDiffs(
        this.restorePreviewSnapshot.beforeSnapshotData || {},
        this.restorePreviewSnapshot.afterSnapshotData || {},
        [],
        {
          beforeLabel: this.$t("agentSnapshot.beforeRestore"),
          afterLabel: this.$t("agentSnapshot.afterRestore"),
          beforeVersionNo: this.restorePreviewSnapshot.beforeVersionNo || this.resolveCurrentVersionNo(),
          afterVersionNo: this.restorePreviewSnapshot.afterVersionNo || this.restorePreviewSnapshot.versionNo,
          fieldOrder: this.restorePreviewSnapshot.fieldOrder
        }
      );
    },
    restoreWillClearChatHistory() {
      return this.restorePreviewSnapshot?.afterSnapshotData?.memModelId === "Memory_nomem";
    },
    restoreTargetVersion() {
      return this.restorePreviewSnapshot?.versionNo || this.restorePreviewRow?.versionNo || "";
    }
  },
  watch: {
    currentVersionNo(newValue, oldValue) {
      if (this.visible && newValue !== oldValue) {
        this.historyAnchorVersionNo = null;
        this.fetchSnapshots({ clearTable: false });
      }
    }
  },
  beforeDestroy() {
    this.cancelPendingSnapshotRequests();
  },
  methods: {
    buildDiffs(beforeData, afterData, changedFields, options = {}) {
      const fields = this.resolveDiffFields(beforeData, afterData, changedFields, options.fieldOrder);
      return fields.map((field) => {
        const beforeValue = this.getFieldValue(beforeData, field);
        const afterValue = this.getFieldValue(afterData, field);
        const displayType = this.displayType(field);
        return {
          field,
          label: this.fieldLabel(field),
          beforeValue,
          afterValue,
          beforeText: this.formatDisplayValue(field, beforeValue, beforeData),
          afterText: this.formatDisplayValue(field, afterValue, afterData),
          displayType,
          beforeTitle: this.formatPaneTitle(options.beforeLabel || this.$t("agentSnapshot.before"), options.beforeVersionNo),
          afterTitle: this.formatPaneTitle(options.afterLabel || this.$t("agentSnapshot.after"), options.afterVersionNo),
          functionChanges: displayType === "functions"
            ? this.buildFunctionChanges(beforeValue, afterValue)
            : [],
          complex: this.isComplexValue(beforeValue) || this.isComplexValue(afterValue)
        };
      });
    },
    close() {
      this.cancelPendingSnapshotRequests();
      this.historyAnchorVersionNo = null;
      this.$emit("update:visible", false);
    },
    open() {
      this.historyAnchorVersionNo = null;
      this.page = 1;
      this.fetchSnapshots();
    },
    cancelPendingSnapshotRequests() {
      this.snapshotFetchSeq += 1;
      this.detailFetchSeq += 1;
      this.restorePreviewFetchSeq += 1;
      this.restoreActionSeq += 1;
      this.deleteActionSeq += 1;
      this.loading = false;
      this.detailLoading = false;
      this.restorePreviewLoading = false;
      this.restoring = false;
      this.deletingSnapshotId = null;
    },
    snapshotRowKey(row) {
      if (row?.isCurrentVersion) {
        return "current-version";
      }
      return row?.id || `${row?.versionNo || ""}-${row?.createdAt || ""}`;
    },
    snapshotRowClassName({ row }) {
      return row?.isCurrentVersion ? "current-version-row" : "";
    },
    canViewSnapshot(row) {
      return !!row && (row.isCurrentVersion || row.previousSnapshotId || row.previousVersionNo);
    },
    canRestoreSnapshot(row) {
      return !!row && !row.isCurrentVersion;
    },
    canDeleteSnapshot(row) {
      return !!row && !row.isCurrentVersion && !row.isLatestSnapshot;
    },
    fetchSnapshots(options = {}) {
      if (!this.agentId) {
        this.snapshots = [];
        this.total = 0;
        this.historyTotal = 0;
        return;
      }
      const { clearTable = true } = options;
      const requestSeq = ++this.snapshotFetchSeq;
      const displayStart = (this.page - 1) * this.limit;
      const displayEnd = displayStart + this.limit;
      const historyFetchLimit = Math.max(displayEnd + 1, this.limit, 1);
      this.ensurePluginMetadata();
      this.ensureModelMetadata();
      this.loading = true;
      if (clearTable) {
        this.snapshots = [];
      }
      Api.agent.getAgentSnapshots(
        this.agentId,
        this.snapshotQueryParams({ page: "1", limit: String(historyFetchLimit) }),
        ({ data }) => {
          if (requestSeq !== this.snapshotFetchSeq) {
            return;
          }
          this.loading = false;
          if (data.code === 0) {
            const historyRows = this.decorateSnapshotRows(data.data?.list || []);
            if (!this.historyAnchorVersionNo && historyRows[0]?.versionNo) {
              this.historyAnchorVersionNo = Number(historyRows[0].versionNo);
            }
            const currentRow = this.buildCurrentVersionRow(historyRows[0]);
            const historyOffset = currentRow ? 1 : 0;
            this.historyTotal = data.data?.total || 0;
            this.total = this.historyTotal + historyOffset;
            if (this.page === 1) {
              const firstPageRows = historyRows.slice(0, currentRow ? this.limit - 1 : this.limit);
              this.snapshots = [
                ...(currentRow ? [currentRow] : []),
                ...this.applyPreviousChangedFields(firstPageRows, historyRows)
              ];
            } else {
              const historyStart = Math.max(displayStart - historyOffset, 0);
              const historyEnd = Math.max(displayEnd - historyOffset, 0);
              this.snapshots = this.applyPreviousChangedFields(
                historyRows.slice(historyStart, historyEnd),
                historyRows
              );
            }
          } else {
            this.$message.error(data.msg || this.$t("agentSnapshot.fetchFailed"));
          }
        }
      );
    },
    handlePageChange(page) {
      this.page = page;
      this.fetchSnapshots();
    },
    viewSnapshot(row) {
      if (!this.canViewSnapshot(row)) {
        return;
      }
      this.detailVisible = true;
      this.detailLoading = true;
      this.currentSnapshot = null;
      const requestSeq = ++this.detailFetchSeq;
      this.ensurePluginMetadata();
      this.ensureModelMetadata();
      this.buildVersionDiffSnapshot(row)
        .then((snapshot) => this.ensureDisplayMetadata(snapshot).then(() => snapshot))
        .then((snapshot) => {
          if (requestSeq !== this.detailFetchSeq) {
            return;
          }
          this.currentSnapshot = snapshot;
        })
        .catch(() => {
          if (requestSeq !== this.detailFetchSeq) {
            return;
          }
          this.$message.error(this.$t("agentSnapshot.detailFailed"));
        })
        .finally(() => {
          if (requestSeq === this.detailFetchSeq) {
            this.detailLoading = false;
          }
        });
    },
    restoreSnapshot(row) {
      if (!this.canRestoreSnapshot(row)) {
        return;
      }
      this.restorePreviewVisible = true;
      this.restorePreviewLoading = true;
      this.restorePreviewRow = row;
      this.restorePreviewSnapshot = null;
      const requestSeq = ++this.restorePreviewFetchSeq;
      this.ensurePluginMetadata();
      this.ensureModelMetadata();

      Promise.all([
        this.fetchSnapshotDetail(row.id),
        this.fetchCurrentAgentData()
      ]).then(([targetSnapshot, currentData]) => {
        if (requestSeq !== this.restorePreviewFetchSeq) {
          return Promise.resolve();
        }
        const previewSnapshot = {
          ...targetSnapshot,
          beforeSnapshotData: currentData,
          afterSnapshotData: targetSnapshot.snapshotData || {},
          beforeVersionNo: this.resolveCurrentVersionNo(),
          afterVersionNo: targetSnapshot.versionNo,
          fieldOrder: targetSnapshot.fieldOrder || []
        };
        return this.ensureDisplayMetadata(previewSnapshot).then(() => {
          if (requestSeq !== this.restorePreviewFetchSeq) {
            return;
          }
          this.restorePreviewSnapshot = previewSnapshot;
        });
      }).catch(() => {
        if (requestSeq !== this.restorePreviewFetchSeq) {
          return;
        }
        this.restorePreviewVisible = false;
        this.$message.error(this.$t("agentSnapshot.detailFailed"));
      }).finally(() => {
        if (requestSeq === this.restorePreviewFetchSeq) {
          this.restorePreviewLoading = false;
        }
      });
    },
    decorateSnapshotRows(rows) {
      return (rows || []).map((row, index) => ({
        ...row,
        isLatestSnapshot: index === 0
      }));
    },
    confirmRestoreSnapshot() {
      if (!this.restorePreviewRow) {
        return;
      }
      this.restoring = true;
      const requestSeq = ++this.restoreActionSeq;
      Api.agent.restoreAgentSnapshot(this.agentId, this.restorePreviewRow.id, ({ data }) => {
        if (requestSeq !== this.restoreActionSeq) {
          return;
        }
        this.restoring = false;
        if (data.code === 0) {
          this.$message.success(this.$t("agentSnapshot.restoreSuccess"));
          this.restorePreviewVisible = false;
          this.detailVisible = false;
          this.$emit("restored");
          this.historyAnchorVersionNo = null;
          this.fetchSnapshots();
        } else {
          this.$message.error(this.restoreFailedMessage(data));
        }
      });
    },
    deleteSnapshot(row) {
      if (!this.canDeleteSnapshot(row)) {
        return;
      }
      this.$confirm(
        this.$t("agentSnapshot.deleteConfirm", { version: row.versionNo }),
        this.$t("common.warning"),
        {
          confirmButtonText: this.$t("common.confirm"),
          cancelButtonText: this.$t("common.cancel"),
          type: "warning"
        }
      ).then(() => {
        const requestSeq = ++this.deleteActionSeq;
        this.deletingSnapshotId = row.id;
        Api.agent.deleteAgentSnapshot(this.agentId, row.id, ({ data }) => {
          if (requestSeq !== this.deleteActionSeq) {
            return;
          }
          this.deletingSnapshotId = null;
          if (data.code === 0) {
            this.$message.success(this.$t("agentSnapshot.deleteSuccess"));
            const savedRowsOnPage = this.snapshots.filter((item) => !item.isCurrentVersion);
            if (savedRowsOnPage.length <= 1 && this.page > 1) {
              this.page -= 1;
            }
            this.fetchSnapshots();
          } else {
            this.$message.error(data.msg || this.$t("agentSnapshot.deleteFailed"));
          }
        });
      }).catch(() => {});
    },
    hasAfterSnapshotData(snapshot) {
      return !!(
        snapshot &&
        snapshot.afterSnapshotData &&
        Object.keys(snapshot.afterSnapshotData).length > 0
      );
    },
    resolveCurrentVersionNo() {
      const propVersionNo = Number(this.currentVersionNo);
      if (Number.isFinite(propVersionNo) && propVersionNo > 0) {
        return propVersionNo;
      }

      const currentRow = this.snapshots.find((item) => item.isCurrentVersion);
      if (currentRow?.versionNo) {
        return currentRow.versionNo;
      }

      return null;
    },
    formatPaneTitle(label, versionNo) {
      return versionNo ? `${label} #${versionNo}` : label;
    },
    formatVersionRangeTitle(label, beforeVersionNo, afterVersionNo) {
      if (beforeVersionNo && afterVersionNo) {
        return `${label} #${beforeVersionNo} → #${afterVersionNo}`;
      }
      if (beforeVersionNo) {
        return `${label} #${beforeVersionNo}`;
      }
      if (afterVersionNo) {
        return `${label} #${afterVersionNo}`;
      }
      return label;
    },
    fetchSnapshotDetail(snapshotId) {
      return new Promise((resolve, reject) => {
        Api.agent.getAgentSnapshot(this.agentId, snapshotId, ({ data }) => {
          if (data.code === 0) {
            resolve(data.data);
          } else {
            reject(data);
          }
        });
      });
    },
    fetchSnapshotRows(params) {
      return new Promise((resolve, reject) => {
        Api.agent.getAgentSnapshots(this.agentId, this.snapshotQueryParams(params), ({ data }) => {
          if (data.code === 0) {
            resolve(data.data || { list: [], total: 0 });
          } else {
            reject(data);
          }
        });
      });
    },
    snapshotQueryParams(params = {}) {
      if (!this.historyAnchorVersionNo) {
        return params;
      }
      return {
        ...params,
        maxVersionNo: String(this.historyAnchorVersionNo)
      };
    },
    applyPreviousChangedFields(rows, sourceRows) {
      return rows.map((row) => {
        const versionNo = Number(row.versionNo);
        if (!Number.isFinite(versionNo) || versionNo <= 1) {
          return {
            ...row,
            changedFields: []
          };
        }
        const previousRow = this.findPreviousSnapshotRow(row, sourceRows);
        return {
          ...row,
          previousSnapshotId: previousRow?.id || null,
          previousVersionNo: previousRow?.versionNo || null,
          changedFields: previousRow?.changedFields || []
        };
      });
    },
    findPreviousSnapshotRow(row, sourceRows) {
      const versionNo = Number(row?.versionNo);
      if (!Number.isFinite(versionNo)) {
        return null;
      }
      return (sourceRows || []).find((item) => {
        return !item.isCurrentVersion && Number(item.versionNo) < versionNo;
      }) || null;
    },
    buildCurrentVersionRow(latestSnapshot) {
      const latestVersionNo = Number(latestSnapshot?.versionNo) || 0;
      const propVersionNo = Number(this.currentVersionNo);
      if (!Number.isFinite(propVersionNo) || propVersionNo <= latestVersionNo) {
        return null;
      }
      return {
        id: "__current__",
        agentId: this.agentId,
        versionNo: propVersionNo,
        source: "current",
        createdAt: latestSnapshot?.createdAt || null,
        changedFields: latestSnapshot?.changedFields || [],
        fieldOrder: latestSnapshot?.fieldOrder || [],
        isCurrentVersion: true,
        previousVersionNo: latestVersionNo || null,
        previousSnapshotId: latestSnapshot?.id || null
      };
    },
    buildVersionDiffSnapshot(row) {
      if (row?.isCurrentVersion) {
        return this.buildCurrentVersionDiffSnapshot(row);
      }
      return this.buildSavedVersionDiffSnapshot(row);
    },
    buildCurrentVersionDiffSnapshot(row) {
      const currentVersionNo = Number(row.versionNo);
      return Promise.all([
        this.fetchPreviousSnapshotDetail(row),
        this.fetchCurrentAgentData()
      ]).then(([previousSnapshot, currentData]) => ({
        ...row,
        versionNo: currentVersionNo,
        changedFields: previousSnapshot.changedFields || [],
        snapshotData: previousSnapshot.snapshotData || {},
        afterSnapshotData: currentData,
        beforeVersionNo: previousSnapshot.versionNo,
        afterVersionNo: currentVersionNo,
        fieldOrder: previousSnapshot.fieldOrder || row.fieldOrder || []
      }));
    },
    buildSavedVersionDiffSnapshot(row) {
      const versionNo = Number(row.versionNo);
      return Promise.all([
        this.fetchSnapshotDetail(row.id),
        this.fetchPreviousSnapshotDetail(row)
      ]).then(([selectedSnapshot, previousSnapshot]) => ({
        ...selectedSnapshot,
        versionNo,
        changedFields: previousSnapshot.changedFields || [],
        snapshotData: previousSnapshot.snapshotData || {},
        afterSnapshotData: selectedSnapshot.snapshotData || {},
        beforeVersionNo: previousSnapshot.versionNo,
        afterVersionNo: versionNo,
        fieldOrder: selectedSnapshot.fieldOrder || previousSnapshot.fieldOrder || row.fieldOrder || []
      }));
    },
    fetchPreviousSnapshotDetail(row) {
      if (row?.previousSnapshotId) {
        return this.fetchSnapshotDetail(row.previousSnapshotId);
      }
      if (row?.previousVersionNo) {
        return this.fetchSnapshotDetailByVersion(row.previousVersionNo);
      }
      return this.fetchSnapshotRowBeforeVersion(row?.versionNo).then((previousRow) => {
        if (!previousRow?.id) {
          return Promise.reject(new Error("previous snapshot not found"));
        }
        return this.fetchSnapshotDetail(previousRow.id);
      });
    },
    fetchSnapshotDetailByVersion(versionNo) {
      return this.fetchSnapshotRowByVersion(versionNo).then((row) => {
        if (!row?.id) {
          return Promise.reject(new Error("snapshot not found"));
        }
        return this.fetchSnapshotDetail(row.id);
      });
    },
    fetchSnapshotRowByVersion(versionNo) {
      const version = Number(versionNo);
      if (!Number.isFinite(version) || version < 1) {
        return Promise.resolve(null);
      }

      const cached = this.snapshots.find((item) => {
        return !item.isCurrentVersion && Number(item.versionNo) === version;
      });
      if (cached) {
        return Promise.resolve(cached);
      }

      const pageNo = this.historyTotal > 0
        ? Math.max(Math.floor((this.historyTotal - version) / this.limit) + 1, 1)
        : 1;
      return this.fetchSnapshotRows({
        page: String(pageNo),
        limit: String(this.limit)
      }).then((data) => {
        const row = (data.list || []).find((item) => Number(item.versionNo) === version);
        if (row || !this.historyTotal || this.historyTotal <= this.limit) {
          return row || null;
        }
        return this.fetchSnapshotRows({
          page: "1",
          limit: String(this.historyTotal)
        }).then((fallbackData) => {
          return (fallbackData.list || []).find((item) => Number(item.versionNo) === version) || null;
        });
      });
    },
    fetchSnapshotRowBeforeVersion(versionNo) {
      const cached = this.findPreviousSnapshotRow({ versionNo }, this.snapshots);
      if (cached) {
        return Promise.resolve(cached);
      }

      return this.fetchSnapshotRows({
        page: "1",
        limit: String(Math.max(this.historyTotal, this.limit, 1))
      }).then((data) => this.findPreviousSnapshotRow({ versionNo }, data.list || []));
    },
    ensurePluginMetadata() {
      if (this.pluginMetadataLoaded) {
        return Promise.resolve();
      }
      if (this.pluginMetadataLoading) {
        return this.pluginMetadataLoading;
      }

      this.pluginMetadataLoading = new Promise((resolve) => {
        Api.model.getPluginFunctionList(null, ({ data }) => {
          if (data.code === 0) {
            const metadata = {};
            (data.data || []).forEach((item) => {
              metadata[item.id] = {
                ...item,
                fieldsMeta: this.parsePluginFields(item.fields)
              };
            });
            this.pluginMetadata = metadata;
            this.pluginMetadataLoaded = true;
          }
          resolve();
        });
      }).finally(() => {
        this.pluginMetadataLoading = null;
      });

      return this.pluginMetadataLoading;
    },
    ensureModelMetadata() {
      if (this.modelMetadataLoaded) {
        return Promise.resolve();
      }
      if (this.modelMetadataLoading) {
        return this.modelMetadataLoading;
      }

      const fetchers = MODEL_TYPES.map((type) => {
        return new Promise((resolve) => {
          const callback = ({ data }) => {
            if (data.code === 0) {
              resolve((data.data || []).map((item) => ({
                id: item.id,
                name: item.modelName
              })));
            } else {
              resolve([]);
            }
          };

          if (type === "LLM") {
            Api.model.getLlmModelCodeList("", callback);
          } else {
            Api.model.getModelNames(type, "", callback);
          }
        });
      });

      this.modelMetadataLoading = Promise.all(fetchers)
        .then((groups) => {
          const metadata = {};
          groups.flat().forEach((item) => {
            if (item.id) {
              metadata[item.id] = item.name || item.id;
            }
          });
          this.modelNameMap = metadata;
          this.modelMetadataLoaded = true;
        })
        .finally(() => {
          this.modelMetadataLoading = null;
        });

      return this.modelMetadataLoading;
    },
    ensureDisplayMetadata(snapshot) {
      const beforeData = snapshot.beforeSnapshotData || snapshot.snapshotData || {};
      const afterData = snapshot.afterSnapshotData || {};
      return Promise.all([
        this.ensureModelMetadata(),
        this.ensureVoiceMetadataForData(beforeData, afterData)
      ]);
    },
    ensureVoiceMetadataForData(...dataList) {
      const modelIds = Array.from(new Set(
        dataList
          .map((data) => data && data.ttsModelId)
          .filter(Boolean)
      ));

      return Promise.all(modelIds.map((modelId) => this.ensureVoiceMetadata(modelId)));
    },
    ensureVoiceMetadata(modelId) {
      if (!modelId || this.loadedVoiceModelIds[modelId]) {
        return Promise.resolve();
      }
      if (this.voiceMetadataLoading[modelId]) {
        return this.voiceMetadataLoading[modelId];
      }

      this.voiceMetadataLoading = {
        ...this.voiceMetadataLoading,
        [modelId]: new Promise((resolve) => {
          Api.model.getModelVoices(modelId, "", ({ data }) => {
            if (data.code === 0) {
              const nextVoiceNameMap = { ...this.voiceNameMap };
              (data.data || []).forEach((voice) => {
                if (voice.id) {
                  nextVoiceNameMap[voice.id] = voice.name || voice.id;
                  nextVoiceNameMap[`${modelId}:${voice.id}`] = voice.name || voice.id;
                }
              });
              this.voiceNameMap = nextVoiceNameMap;
              this.loadedVoiceModelIds = {
                ...this.loadedVoiceModelIds,
                [modelId]: true
              };
            }
            resolve();
          });
        }).finally(() => {
          const { [modelId]: dropped, ...rest } = this.voiceMetadataLoading;
          this.voiceMetadataLoading = rest;
        })
      };

      return this.voiceMetadataLoading[modelId];
    },
    parsePluginFields(fields) {
      if (!fields) {
        return [];
      }
      if (Array.isArray(fields)) {
        return fields;
      }
      if (typeof fields === "string") {
        try {
          const parsed = JSON.parse(fields);
          return Array.isArray(parsed) ? parsed : [];
        } catch (error) {
          return [];
        }
      }
      return [];
    },
    fetchCurrentAgentData() {
      const configPromise = new Promise((resolve, reject) => {
        Api.agent.getDeviceConfig(this.agentId, ({ data }) => {
          if (data.code === 0) {
            resolve(data.data || {});
          } else {
            reject(data);
          }
        });
      });
      const tagsPromise = this.fetchCurrentAgentTags();

      return Promise.all([configPromise, tagsPromise]).then(([data, tags]) => {
        return this.normalizeAgentData({
          ...data,
          tags,
          tagNames: tags.map((tag) => tag.tagName)
        });
      });
    },
    fetchCurrentAgentTags() {
      return new Promise((resolve, reject) => {
        Api.agent.getAgentTags(this.agentId, ({ data }) => {
          if (data.code === 0) {
            resolve(data.data || []);
          } else {
            reject(data);
          }
        });
      });
    },
    normalizeAgentData(data) {
      const tags = data.tags || [];
      return {
        ...data,
        functions: (data.functions || []).map((item) => ({
          pluginId: item.pluginId,
          paramInfo: this.parseParamInfo(item.paramInfo)
        })),
        tags,
        tagNames: data.tagNames || tags.map((tag) => tag.tagName)
      };
    },
    parseParamInfo(paramInfo) {
      if (!paramInfo) {
        return {};
      }
      if (typeof paramInfo === "string") {
        try {
          return JSON.parse(paramInfo);
        } catch (error) {
          return {};
        }
      }
      return paramInfo;
    },
    displayType(field) {
      if (field === "functions") {
        return "functions";
      }
      if (field === "systemPrompt") {
        return "markdown";
      }
      return "text";
    },
    valueClass(item) {
      return [`is-${item.displayType || "text"}`];
    },
    normalizeFunctions(value) {
      return Object.values(this.normalizeFunctionMap(value)).map((item) => ({
        pluginId: item.pluginId,
        name: this.functionDisplayName(item.pluginId),
        params: this.functionParamRows(item.pluginId, item.params)
      }));
    },
    normalizeFunctionList(value) {
      if (!value) {
        return [];
      }
      if (typeof value === "string") {
        try {
          const parsed = JSON.parse(value);
          return Array.isArray(parsed) ? parsed : [];
        } catch (error) {
          return [];
        }
      }
      return Array.isArray(value) ? value : [];
    },
    normalizeFunctionParams(value) {
      if (!value) {
        return {};
      }
      if (typeof value === "string") {
        try {
          const parsed = JSON.parse(value);
          return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
        } catch (error) {
          return {};
        }
      }
      return value && typeof value === "object" && !Array.isArray(value) ? value : {};
    },
    normalizeFunctionMap(value) {
      return this.normalizeFunctionList(value).reduce((result, item) => {
        const pluginId = item.pluginId || item.id || item.providerCode || item.name;
        if (!pluginId) {
          return result;
        }
        result[pluginId] = {
          pluginId,
          params: this.normalizeFunctionParams(item.paramInfo ?? item.params)
        };
        return result;
      }, {});
    },
    buildFunctionChanges(beforeValue, afterValue) {
      const beforeMap = this.normalizeFunctionMap(beforeValue);
      const afterMap = this.normalizeFunctionMap(afterValue);
      const pluginIds = Array.from(new Set([
        ...Object.keys(beforeMap),
        ...Object.keys(afterMap)
      ]));

      return pluginIds.reduce((changes, pluginId) => {
        const beforeFunc = beforeMap[pluginId];
        const afterFunc = afterMap[pluginId];

        if (!beforeFunc && afterFunc) {
          changes.push(this.createFunctionChange("added", null, afterFunc));
          return changes;
        }

        if (beforeFunc && !afterFunc) {
          changes.push(this.createFunctionChange("removed", beforeFunc, null));
          return changes;
        }

        const changedParamKeys = this.changedFunctionParamKeys(
          pluginId,
          beforeFunc.params,
          afterFunc.params
        );
        if (changedParamKeys.length) {
          changes.push(this.createFunctionChange("updated", beforeFunc, afterFunc, changedParamKeys));
        }
        return changes;
      }, []);
    },
    createFunctionChange(type, beforeFunc, afterFunc, changedParamKeys = []) {
      const pluginId = (afterFunc || beforeFunc).pluginId;
      const name = this.functionDisplayName(pluginId);
      const statusMap = {
        added: {
          badge: this.$t("agentSnapshot.function.added")
        },
        removed: {
          badge: this.$t("agentSnapshot.function.removed")
        },
        updated: {
          badge: this.$t("agentSnapshot.function.updated")
        }
      };
      return {
        type,
        pluginId,
        name,
        ...statusMap[type],
        before: this.buildFunctionState(pluginId, beforeFunc, changedParamKeys),
        after: this.buildFunctionState(pluginId, afterFunc, changedParamKeys)
      };
    },
    buildFunctionState(pluginId, func, changedParamKeys = []) {
      if (!func) {
        return {
          active: false,
          status: this.$t("agentSnapshot.function.disabled"),
          params: [],
          note: this.$t("agentSnapshot.function.disabledNote")
        };
      }

      const params = this.functionParamRows(pluginId, func.params, changedParamKeys);
      return {
        active: true,
        status: this.$t("agentSnapshot.function.enabled"),
        params,
        note: params.length ? "" : this.$t("agentSnapshot.function.noParams")
      };
    },
    changedFunctionParamKeys(pluginId, beforeParams, afterParams) {
      const safeBeforeParams = beforeParams || {};
      const safeAfterParams = afterParams || {};
      const paramKeys = Array.from(new Set([
        ...Object.keys(safeBeforeParams),
        ...Object.keys(safeAfterParams)
      ]));

      return paramKeys.reduce((keys, key) => {
        if (this.isSameValue(safeBeforeParams[key], safeAfterParams[key])) {
          return keys;
        }
        keys.push(key);
        return keys;
      }, []);
    },
    functionParamRows(pluginId, params, changedParamKeys = []) {
      const normalizedParams = params || {};
      const fieldKeys = this.functionFields(pluginId).map((field) => field.key);
      const paramKeys = Array.from(new Set([
        ...fieldKeys,
        ...Object.keys(normalizedParams)
      ])).filter((key) => key);

      return paramKeys.map((key) => ({
        key,
        label: this.functionParamLabel(pluginId, key),
        value: this.formatFunctionParamValue(normalizedParams[key]),
        changed: changedParamKeys.includes(key)
      }));
    },
    functionDisplayName(pluginId) {
      const meta = this.resolveFunctionMeta(pluginId);
      return meta?.name || this.translateKey(FALLBACK_PLUGIN_NAME_KEYS[pluginId], pluginId)
        || pluginId || this.$t("agentSnapshot.emptyValue");
    },
    functionParamLabel(pluginId, key) {
      const field = this.functionFields(pluginId).find((item) => item.key === key);
      return field?.label || this.translateKey(FALLBACK_FIELD_LABEL_KEYS[key], key) || key;
    },
    functionFields(pluginId) {
      const meta = this.resolveFunctionMeta(pluginId);
      return Array.isArray(meta?.fieldsMeta) ? meta.fieldsMeta : [];
    },
    resolveFunctionMeta(pluginId) {
      if (!pluginId) {
        return null;
      }
      if (this.pluginMetadata[pluginId]) {
        return this.pluginMetadata[pluginId];
      }
      return Object.values(this.pluginMetadata).find((item) => {
        return item.id === pluginId || item.providerCode === pluginId || item.name === pluginId;
      }) || null;
    },
    formatFunctionParamValue(value) {
      if (value === null || value === undefined || value === "") {
        return this.$t("agentSnapshot.emptyValue");
      }
      if (typeof value === "object") {
        return JSON.stringify(value);
      }
      return String(value);
    },
    renderMarkdownValue(value) {
      if (value === null || value === undefined || String(value).trim() === "") {
        return `<span class="markdown-empty">${this.escapeHtml(this.$t("agentSnapshot.emptyValue"))}</span>`;
      }

      const lines = String(value).replace(/\r\n/g, "\n").split("\n");
      const html = [];
      let paragraph = [];
      const listStack = [];

      const closeParagraph = () => {
        if (paragraph.length) {
          html.push(`<p>${paragraph.map((line) => this.renderInlineMarkdown(line)).join("<br>")}</p>`);
          paragraph = [];
        }
      };
      const closeOneList = () => {
        const list = listStack.pop();
        if (!list) {
          return;
        }
        if (list.liOpen) {
          html.push("</li>");
        }
        html.push(`</${list.type}>`);
      };
      const closeLists = () => {
        while (listStack.length) {
          closeOneList();
        }
      };
      const openList = (type, indent) => {
        html.push(`<${type}>`);
        listStack.push({ type, indent, liOpen: false });
      };
      const alignList = (type, indent) => {
        while (listStack.length && indent < listStack[listStack.length - 1].indent) {
          closeOneList();
        }

        let current = listStack[listStack.length - 1];
        if (current && indent === current.indent && type !== current.type) {
          closeOneList();
        }

        current = listStack[listStack.length - 1];
        if (!current || indent > current.indent || indent !== current.indent) {
          openList(type, indent);
        }
      };
      const addListItem = (type, indent, text) => {
        closeParagraph();
        alignList(type, indent);
        const current = listStack[listStack.length - 1];
        if (current.liOpen) {
          html.push("</li>");
        }
        html.push(`<li>${this.renderInlineMarkdown(text)}`);
        current.liOpen = true;
      };

      lines.forEach((rawLine) => {
        const normalizedLine = rawLine.replace(/\t/g, "  ");
        const line = normalizedLine.trim();
        if (!line) {
          closeParagraph();
          closeLists();
          return;
        }

        const heading = line.match(/^(#{1,6})\s+(.+)$/);
        if (heading) {
          closeParagraph();
          closeLists();
          const level = Math.min(heading[1].length, 4);
          html.push(`<h${level}>${this.renderInlineMarkdown(heading[2])}</h${level}>`);
          return;
        }

        const indent = normalizedLine.match(/^ */)[0].length;
        const listContent = normalizedLine.slice(indent);
        const unordered = listContent.match(/^[-*+]\s+(.+)$/);
        if (unordered) {
          addListItem("ul", indent, unordered[1]);
          return;
        }

        const ordered = listContent.match(/^\d+\.\s+(.+)$/);
        if (ordered) {
          addListItem("ol", indent, ordered[1]);
          return;
        }

        closeLists();
        paragraph.push(line);
      });

      closeParagraph();
      closeLists();
      return html.join("");
    },
    renderInlineMarkdown(value) {
      return this.escapeHtml(value)
        .replace(/`([^`]+)`/g, "<code>$1</code>")
        .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
        .replace(/__([^_]+)__/g, "<strong>$1</strong>")
        .replace(/\*([^*]+)\*/g, "<em>$1</em>");
    },
    escapeHtml(value) {
      return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
    },
    restoreFailedMessage(data) {
      return data?.msg
        ? `${this.$t("agentSnapshot.restoreFailedRollback")}: ${data.msg}`
        : this.$t("agentSnapshot.restoreFailedRollback");
    },
    resolveDiffFields(beforeData, afterData, changedFields = [], fieldOrder = []) {
      const safeChangedFields = Array.isArray(changedFields) ? changedFields : [];
      const directFields = safeChangedFields
        .filter((field) => field && field !== "restore")
        .map((field) => this.canonicalField(field));
      const candidates = directFields.length > 0 && !safeChangedFields.includes("restore")
        ? directFields
        : this.snapshotFieldOrder(fieldOrder, beforeData, afterData);

      return Array.from(new Set(candidates)).filter((field) => {
        return !this.isSameValue(
          this.getFieldValue(beforeData, field),
          this.getFieldValue(afterData, field)
        );
      });
    },
    snapshotFieldOrder(fieldOrder = [], beforeData = {}, afterData = {}) {
      const backendOrder = Array.isArray(fieldOrder) ? fieldOrder : [];
      if (backendOrder.length) {
        return backendOrder.map((field) => this.canonicalField(field));
      }
      const dataFields = [
        ...Object.keys(beforeData || {}),
        ...Object.keys(afterData || {})
      ].map((field) => this.canonicalField(field));
      return Array.from(new Set(dataFields)).filter((field) => field !== "tags");
    },
    canonicalField(field) {
      return field === "tags" || field === "tagIds" ? "tagNames" : field;
    },
    getFieldValue(data, field) {
      if (!data) {
        return null;
      }
      if (field === "tagNames") {
        return data.tagNames || (data.tags || []).map((tag) => tag.tagName);
      }
      if (field === "tagIds") {
        return (data.tags || []).map((tag) => tag.id).filter(Boolean);
      }
      return data[field];
    },
    isSameValue(left, right) {
      return JSON.stringify(this.normalizeValue(left)) === JSON.stringify(this.normalizeValue(right));
    },
    normalizeValue(value) {
      if (Array.isArray(value)) {
        return value.map((item) => this.normalizeValue(item));
      }
      if (value && typeof value === "object") {
        return Object.keys(value).sort().reduce((result, key) => {
          result[key] = this.normalizeValue(value[key]);
          return result;
        }, {});
      }
      return value === undefined ? null : value;
    },
    formatDisplayValue(field, value, data = {}) {
      if (MODEL_FIELD_TYPES[field]) {
        return this.modelDisplayName(value);
      }
      if (field === "ttsVoiceId") {
        return this.voiceDisplayName(data.ttsModelId, value);
      }
      if (field === "chatHistoryConf") {
        return this.translateKey(CHAT_HISTORY_CONF_LABEL_KEYS[value] || CHAT_HISTORY_CONF_LABEL_KEYS[Number(value)])
          || this.formatValue(value);
      }
      return this.formatValue(value);
    },
    modelDisplayName(value) {
      if (value === null || value === undefined || value === "") {
        return this.$t("agentSnapshot.emptyValue");
      }
      return this.modelNameMap[value] || this.translateKey(FALLBACK_MODEL_NAME_KEYS[value], String(value)) || String(value);
    },
    voiceDisplayName(modelId, value) {
      if (value === null || value === undefined || value === "") {
        return this.$t("agentSnapshot.emptyValue");
      }
      return this.voiceNameMap[`${modelId}:${value}`] || this.voiceNameMap[value]
        || this.translateKey(FALLBACK_VOICE_NAME_KEYS[value], String(value)) || String(value);
    },
    formatValue(value) {
      if (value === null || value === undefined || value === "") {
        return this.$t("agentSnapshot.emptyValue");
      }
      if (Array.isArray(value) && value.length === 0) {
        return this.$t("agentSnapshot.emptyValue");
      }
      if (Array.isArray(value) && value.every((item) => this.isPrimitiveValue(item))) {
        return value.join(", ");
      }
      if (this.isComplexValue(value)) {
        return JSON.stringify(value, null, 2);
      }
      return String(value);
    },
    isPrimitiveValue(value) {
      return value === null || ["string", "number", "boolean"].includes(typeof value);
    },
    isComplexValue(value) {
      return value !== null && typeof value === "object";
    },
    formatTime(value) {
      return formatDate(value);
    },
    sourceLabel(source) {
      const key = `agentSnapshot.source.${source || "config"}`;
      return this.$te && this.$te(key) ? this.$t(key) : source;
    },
    fieldLabel(field) {
      const key = `agentSnapshot.field.${field}`;
      return this.$te && this.$te(key) ? this.$t(key) : field;
    },
    translateKey(key, fallback = "") {
      return key && this.$te && this.$te(key) ? this.$t(key) : fallback;
    }
  }
};
</script>

<style lang="scss" scoped>
@import '@/styles/global.scss';

::v-deep .el-dialog {
  margin-top: 6vh !important;
  border-radius: 10px;
  overflow: hidden;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

::v-deep .el-dialog__header {
  padding: 16px 20px 12px;
  background: linear-gradient(135deg, #e2eeff, #edeafe);
  text-align: left;
}

::v-deep .el-dialog__title {
  color: #1a1a1a;
  font-size: 16px;
  font-weight: 500;
}

::v-deep .el-dialog__body {
  padding: 20px;
}

::v-deep .el-dialog__footer {
  padding: 12px 20px 16px;
}

.snapshot-table {
  width: 100%;
}

.version-cell {
  display: inline-flex;
  gap: 6px;
  align-items: center;
  white-space: nowrap;
}

.latest-version-icon {
  flex: 0 0 auto;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #67c23a;
  box-shadow: 0 0 0 3px rgba(103, 194, 58, 0.12);
}

::v-deep .current-version-row {
  background: #fbfffa;
}

.snapshot-delete-button {
  color: #f56c6c;
}

.field-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.field-tags-empty {
  color: #a3a8b8;
}

.pagination-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.snapshot-diff {
  min-height: 220px;
  max-height: 62vh;
  overflow: auto;
  padding-right: 2px;
  @include scrollbar-style;
}

.restore-risk-alert {
  margin-top: 14px;
}

.detail-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 16px;
  color: #606266;
  font-size: 12px;
  text-align: left;
}

.detail-summary span {
  padding: 4px 9px;
  border-radius: 4px;
  background: #f4f6ff;
  color: #4d5b7c;
}

.diff-item {
  margin-bottom: 16px;
  overflow: hidden;
  border: 1px solid #e9e9e9;
  border-radius: 8px;
  background: #fff;
}

.diff-field {
  padding: 12px 16px;
  border-bottom: 1px solid #e9e9e9;
  background: #fafbff;
  color: #3d4566;
  font-size: 16px;
  font-weight: 700;
  text-align: left;
}

.diff-values {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
}

.diff-pane {
  min-width: 0;
  padding: 12px 14px;
  text-align: left;
}

.diff-after {
  border-left: 1px solid #e9e9e9;
}

.diff-pane-title {
  margin-bottom: 8px;
  color: #3d4566;
  font-size: 14px;
  font-weight: 600;
  line-height: 1.4;
  text-align: left;
}

.diff-value {
  box-sizing: border-box;
  min-height: 40px;
  max-height: 260px;
  overflow: auto;
  padding: 9px 12px;
  margin: 0;
  border-radius: 6px;
  font-size: 13px;
  line-height: 1.45;
  word-break: break-word;
  text-align: left;
  @include scrollbar-style;
}

.diff-before .diff-value {
  background: #fff8f8;
  color: #663434;
}

.diff-after .diff-value {
  background: #f7fbf4;
  color: #2d5c3a;
}

.is-complex .diff-value {
  max-height: 340px;
}

.diff-text {
  margin: 0;
  font-family: Menlo, Monaco, Consolas, "Courier New", monospace;
  font-size: 12px;
  line-height: 1.45;
  white-space: pre-wrap;
  text-align: left;
}

.function-change-view {
  padding: 16px;
  background: #fff;
}

.function-toggle-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.function-toggle-card {
  padding: 14px 16px;
  border: 1px solid #dfe7ff;
  border-radius: 8px;
  background: #fbfdff;
  box-shadow: 0 2px 8px rgba(31, 48, 96, 0.04);
}

.function-toggle-card.is-added {
  border-color: #dcefdc;
  background: #fbfffa;
}

.function-toggle-card.is-removed {
  border-color: #f5d6d6;
  background: #fffafa;
}

.function-toggle-card.is-updated {
  border-color: #dfe7ff;
  background: #fbfdff;
}

.function-toggle-head {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}

.function-dot {
  flex: 0 0 auto;
  width: 8px;
  height: 8px;
  margin-top: 7px;
  border-radius: 50%;
  background: #6278ff;
}

.function-toggle-card.is-removed .function-dot {
  background: #f56c6c;
}

.function-toggle-card.is-added .function-dot {
  background: #67c23a;
}

.function-change-title-wrap {
  min-width: 0;
  flex: 1;
}

.function-change-title-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.function-change-name {
  color: #30415f;
  font-size: 16px;
  font-weight: 500;
  line-height: 1.4;
  word-break: break-word;
}

.function-change-badge {
  padding: 2px 8px;
  border-radius: 999px;
  background: #eef4ff;
  color: #4d65d9;
  font-size: 12px;
  line-height: 1.5;
}

.function-toggle-card.is-added .function-change-badge {
  background: #edf8e8;
  color: #4f9b2d;
}

.function-toggle-card.is-removed .function-change-badge {
  background: #fff0f0;
  color: #d24b4b;
}

.function-state-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 10px;
  margin-top: 10px;
}

.function-state-pane {
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid #edf0f7;
  border-radius: 6px;
  background: #fff;
}

.function-state-pane.is-before {
  background: #fffafa;
}

.function-state-pane.is-after {
  background: #fbfffa;
}

.function-state-pane.is-disabled {
  background: #fafbff;
}

.function-state-title {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
  color: #3d4566;
  font-size: 14px;
  font-weight: 600;
}

.function-state-badge {
  flex: 0 0 auto;
  padding: 1px 8px;
  border-radius: 999px;
  background: #edf8e8;
  color: #4f9b2d;
  font-size: 12px;
  font-weight: 400;
  line-height: 1.5;
}

.function-state-pane.is-disabled .function-state-badge {
  background: #f0f2f7;
  color: #8b93a7;
}

.function-state-params {
  display: block;
}

.function-param-row {
  display: grid;
  grid-template-columns: minmax(78px, 118px) minmax(0, 1fr);
  align-items: stretch;
}

.function-param-row + .function-param-row {
  border-top: 1px solid #e6ebf5;
}

.function-param-row.is-changed {
  background: #fff7e6;
}

.param-key {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  min-width: 0;
  min-height: 28px;
  padding: 5px 10px 5px 0;
  color: #69738f;
  font-size: 12px;
  line-height: 1.35;
  text-align: right;
  overflow-wrap: anywhere;
}

.param-value {
  min-width: 0;
  min-height: 28px;
  padding: 5px 0 5px 10px;
  border-left: 1px solid #e6ebf5;
  color: #303133;
  font-family: Menlo, Monaco, Consolas, "Courier New", monospace;
  font-size: 12px;
  line-height: 1.4;
  white-space: pre-wrap;
  word-break: break-word;
}

.function-state-empty {
  color: #a3a8b8;
  font-size: 13px;
  line-height: 1.6;
}

.value-empty {
  color: #a3a8b8;
  font-size: 13px;
}

.markdown-body {
  color: inherit;
  font-size: 13px;
  line-height: 1.7;
  text-align: left;
  white-space: normal;
}

.markdown-body ::v-deep h1,
.markdown-body ::v-deep h2,
.markdown-body ::v-deep h3,
.markdown-body ::v-deep h4 {
  margin: 0 0 8px;
  color: #3d4566;
  font-weight: 700;
  line-height: 1.4;
}

.markdown-body ::v-deep h1 {
  font-size: 18px;
}

.markdown-body ::v-deep h2 {
  font-size: 16px;
}

.markdown-body ::v-deep h3,
.markdown-body ::v-deep h4 {
  font-size: 14px;
}

.markdown-body ::v-deep p {
  margin: 0 0 8px;
}

.markdown-body ::v-deep p:last-child,
.markdown-body ::v-deep ul:last-child,
.markdown-body ::v-deep ol:last-child {
  margin-bottom: 0;
}

.markdown-body ::v-deep ul,
.markdown-body ::v-deep ol {
  margin: 0 0 8px;
  padding-left: 20px;
}

.markdown-body ::v-deep li {
  margin-bottom: 4px;
}

.markdown-body ::v-deep code {
  padding: 1px 4px;
  border-radius: 4px;
  background: rgba(87, 120, 255, 0.12);
  color: #3d4566;
  font-family: Menlo, Monaco, Consolas, "Courier New", monospace;
  font-size: 12px;
}

.markdown-body ::v-deep strong {
  color: #303133;
  font-weight: 700;
}

.markdown-body ::v-deep .markdown-empty {
  color: #a3a8b8;
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

@media (max-width: 720px) {
  .diff-values {
    grid-template-columns: 1fr;
  }

  .diff-after {
    border-left: 0;
    border-top: 1px solid #e9e9e9;
  }

  .function-state-grid,
  .function-param-row {
    grid-template-columns: 1fr;
  }

  .param-key {
    justify-content: flex-start;
    padding: 7px 0 2px;
    text-align: left;
  }

  .param-value {
    min-height: 0;
    padding: 0 0 7px;
    border-left: 0;
  }
}
</style>
