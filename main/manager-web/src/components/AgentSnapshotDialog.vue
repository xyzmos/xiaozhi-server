<template>
  <div>
    <el-dialog
      :title="$t('agentSnapshot.title')"
      :visible="visible"
      width="760px"
      class="agent-snapshot-dialog"
      @open="fetchSnapshots"
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
        <el-table-column :label="$t('agentSnapshot.actions')" width="150" fixed="right">
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
              <div v-else class="value-empty">功能配置无变化</div>
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
              <div v-else class="value-empty">功能配置无变化</div>
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

const FALLBACK_PLUGIN_NAMES = {
  SYSTEM_PLUGIN_WEATHER: "天气查询",
  SYSTEM_PLUGIN_MUSIC: "服务器音乐播放",
  SYSTEM_PLUGIN_NEWS_CHINANEWS: "中新网新闻",
  SYSTEM_PLUGIN_NEWS_NEWSNOW: "newsnow新闻聚合",
  SYSTEM_PLUGIN_HA_GET_STATE: "HomeAssistant设备状态查询",
  SYSTEM_PLUGIN_HA_SET_STATE: "HomeAssistant设备状态修改",
  SYSTEM_PLUGIN_HA_PLAY_MUSIC: "HomeAssistant音乐播放",
  SYSTEM_PLUGIN_WEB_SEARCH: "联网搜索",
  SYSTEM_PLUGIN_CALL_DEVICE: "设备呼叫设备"
};

const FALLBACK_FIELD_LABELS = {
  url: "接口地址",
  news_sources: "新闻源配置",
  default_rss_url: "默认 RSS 源",
  society_rss_url: "社会新闻 RSS 地址",
  world_rss_url: "国际新闻 RSS 地址",
  finance_rss_url: "财经新闻 RSS 地址",
  api_key: "API 密钥",
  default_location: "默认查询城市",
  api_host: "开发者 API Host",
  base_url: "服务器地址",
  devices: "设备列表",
  provider: "搜索源",
  description: "工具描述",
  max_results: "返回数量"
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

const FALLBACK_MODEL_NAMES = {
  Memory_nomem: "无记忆",
  Memory_mem_local_short: "本地短记忆",
  Memory_mem0ai: "Mem0AI记忆",
  Memory_mem_report_only: "仅上报记忆",
  Intent_nointent: "无意图识别",
  Intent_intent_llm: "外挂的大模型意图识别",
  Intent_function_call: "大模型自主函数调用"
};

const FALLBACK_VOICE_NAMES = {
  TTS_EdgeTTS0001: "EdgeTTS女声-晓晓",
  TTS_EdgeTTS0002: "EdgeTTS男声-云扬",
  TTS_EdgeTTS0003: "EdgeTTS女声-晓伊",
  TTS_EdgeTTS0004: "EdgeTTS男声-云健",
  TTS_EdgeTTS0005: "EdgeTTS男声-云希",
  TTS_EdgeTTS0006: "EdgeTTS男声-云夏"
};

const CHAT_HISTORY_CONF_LABELS = {
  0: "不记录聊天记录",
  1: "上报文字",
  2: "上报文字+语音"
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
      pluginMetadata: {},
      pluginMetadataLoaded: false,
      pluginMetadataLoading: null,
      modelNameMap: {},
      modelMetadataLoaded: false,
      modelMetadataLoading: null,
      voiceNameMap: { ...FALLBACK_VOICE_NAMES },
      voiceMetadataLoading: {},
      loadedVoiceModelIds: {},
      snapshotFetchSeq: 0,
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
        beforeLabel: "变化前",
        afterLabel: "变化后",
        beforeVersionNo: this.currentSnapshot.beforeVersionNo,
        afterVersionNo: this.currentSnapshot.afterVersionNo || this.currentSnapshot.versionNo
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
          beforeLabel: "恢复前",
          afterLabel: "恢复后",
          beforeVersionNo: this.restorePreviewSnapshot.beforeVersionNo || this.resolveCurrentVersionNo(),
          afterVersionNo: this.restorePreviewSnapshot.afterVersionNo || this.restorePreviewSnapshot.versionNo
        }
      );
    }
  },
  methods: {
    buildDiffs(beforeData, afterData, changedFields, options = {}) {
      const fields = this.resolveDiffFields(beforeData, afterData, changedFields);
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
      this.snapshotFetchSeq += 1;
      this.loading = false;
      this.$emit("update:visible", false);
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
      return Number(row?.versionNo) > 1;
    },
    canRestoreSnapshot(row) {
      return !!row && !row.isCurrentVersion;
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
      const historyFetchLimit = Math.max(displayEnd, this.limit, 1);
      this.ensurePluginMetadata();
      this.ensureModelMetadata();
      this.loading = true;
      if (clearTable) {
        this.snapshots = [];
      }
      Api.agent.getAgentSnapshots(
        this.agentId,
        { page: "1", limit: String(historyFetchLimit) },
        ({ data }) => {
          if (requestSeq !== this.snapshotFetchSeq) {
            return;
          }
          this.loading = false;
          if (data.code === 0) {
            const historyRows = data.data?.list || [];
            this.historyTotal = data.data?.total || 0;
            this.total = this.historyTotal + 1;
            if (this.page === 1) {
              this.snapshots = [
                this.buildCurrentVersionRow(historyRows[0]),
                ...this.applyPreviousChangedFields(historyRows.slice(0, this.limit - 1), historyRows)
              ];
            } else {
              this.snapshots = this.applyPreviousChangedFields(
                historyRows.slice(displayStart - 1, displayEnd - 1),
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
      this.ensurePluginMetadata();
      this.ensureModelMetadata();
      this.buildVersionDiffSnapshot(row)
        .then((snapshot) => this.ensureDisplayMetadata(snapshot).then(() => snapshot))
        .then((snapshot) => {
          this.currentSnapshot = snapshot;
        })
        .catch(() => {
          this.$message.error(this.$t("agentSnapshot.detailFailed"));
        })
        .finally(() => {
          this.detailLoading = false;
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
      this.ensurePluginMetadata();
      this.ensureModelMetadata();

      Promise.all([
        this.fetchSnapshotDetail(row.id),
        this.fetchCurrentAgentData()
      ]).then(([targetSnapshot, currentData]) => {
        const previewSnapshot = {
          ...targetSnapshot,
          beforeSnapshotData: currentData,
          afterSnapshotData: targetSnapshot.snapshotData || {},
          beforeVersionNo: this.resolveCurrentVersionNo(),
          afterVersionNo: targetSnapshot.versionNo
        };
        return this.ensureDisplayMetadata(previewSnapshot).then(() => {
          this.restorePreviewSnapshot = previewSnapshot;
        });
      }).catch(() => {
        this.restorePreviewVisible = false;
        this.$message.error(this.$t("agentSnapshot.detailFailed"));
      }).finally(() => {
        this.restorePreviewLoading = false;
      });
    },
    confirmRestoreSnapshot() {
      if (!this.restorePreviewRow) {
        return;
      }
      this.restoring = true;
      Api.agent.restoreAgentSnapshot(this.agentId, this.restorePreviewRow.id, ({ data }) => {
        this.restoring = false;
        if (data.code === 0) {
          this.$message.success(this.$t("agentSnapshot.restoreSuccess"));
          this.restorePreviewVisible = false;
          this.detailVisible = false;
          this.$emit("restored");
          this.fetchSnapshots();
        } else {
          this.$message.error(data.msg || this.$t("agentSnapshot.restoreFailed"));
        }
      });
    },
    hasAfterSnapshotData(snapshot) {
      return !!(
        snapshot &&
        snapshot.afterSnapshotData &&
        Object.keys(snapshot.afterSnapshotData).length > 0
      );
    },
    resolveCurrentVersionNo() {
      if (this.currentVersionNo) {
        return this.currentVersionNo;
      }

      const currentRow = this.snapshots.find((item) => item.isCurrentVersion);
      if (currentRow?.versionNo) {
        return currentRow.versionNo;
      }

      const maxVersionNo = Math.max(
        ...this.snapshots
          .filter((item) => !item.isCurrentVersion)
          .map((item) => Number(item.versionNo) || 0)
      );
      return maxVersionNo > 0 ? maxVersionNo + 1 : 1;
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
        Api.agent.getAgentSnapshots(this.agentId, params, ({ data }) => {
          if (data.code === 0) {
            resolve(data.data || { list: [], total: 0 });
          } else {
            reject(data);
          }
        });
      });
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
        const previousRow = sourceRows.find((item) => Number(item.versionNo) === versionNo - 1);
        return {
          ...row,
          changedFields: previousRow?.changedFields || []
        };
      });
    },
    buildCurrentVersionRow(latestSnapshot) {
      const latestVersionNo = Number(latestSnapshot?.versionNo) || 0;
      const propVersionNo = Number(this.currentVersionNo);
      const inferredVersionNo = latestVersionNo + 1 || 1;
      const currentVersionNo = Number.isFinite(propVersionNo) && propVersionNo > latestVersionNo
        ? propVersionNo
        : inferredVersionNo;
      return {
        id: "__current__",
        agentId: this.agentId,
        versionNo: currentVersionNo,
        source: "current",
        createdAt: latestSnapshot?.createdAt || null,
        changedFields: latestSnapshot?.changedFields || [],
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
      const previousVersionNo = currentVersionNo - 1;
      return Promise.all([
        this.fetchSnapshotDetailByVersion(previousVersionNo),
        this.fetchCurrentAgentData()
      ]).then(([previousSnapshot, currentData]) => ({
        ...row,
        versionNo: currentVersionNo,
        changedFields: previousSnapshot.changedFields || [],
        snapshotData: previousSnapshot.snapshotData || {},
        afterSnapshotData: currentData,
        beforeVersionNo: previousVersionNo,
        afterVersionNo: currentVersionNo
      }));
    },
    buildSavedVersionDiffSnapshot(row) {
      const versionNo = Number(row.versionNo);
      const previousVersionNo = versionNo - 1;
      return Promise.all([
        this.fetchSnapshotDetail(row.id),
        this.fetchSnapshotDetailByVersion(previousVersionNo)
      ]).then(([selectedSnapshot, previousSnapshot]) => ({
        ...selectedSnapshot,
        versionNo,
        changedFields: previousSnapshot.changedFields || [],
        snapshotData: previousSnapshot.snapshotData || {},
        afterSnapshotData: selectedSnapshot.snapshotData || {},
        beforeVersionNo: previousVersionNo,
        afterVersionNo: versionNo
      }));
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
          const metadata = { ...FALLBACK_MODEL_NAMES };
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
          badge: "已开启"
        },
        removed: {
          badge: "已关闭"
        },
        updated: {
          badge: "参数变更"
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
          status: "未开启",
          params: [],
          note: "未开启此功能"
        };
      }

      const params = this.functionParamRows(pluginId, func.params, changedParamKeys);
      return {
        active: true,
        status: "已开启",
        params,
        note: params.length ? "" : "无需配置参数"
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
      return meta?.name || FALLBACK_PLUGIN_NAMES[pluginId] || pluginId || this.$t("agentSnapshot.emptyValue");
    },
    functionParamLabel(pluginId, key) {
      const field = this.functionFields(pluginId).find((item) => item.key === key);
      return field?.label || FALLBACK_FIELD_LABELS[key] || key;
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
      let listType = null;

      const closeParagraph = () => {
        if (paragraph.length) {
          html.push(`<p>${paragraph.map((line) => this.renderInlineMarkdown(line)).join("<br>")}</p>`);
          paragraph = [];
        }
      };
      const closeList = () => {
        if (listType) {
          html.push(`</${listType}>`);
          listType = null;
        }
      };
      const openList = (type) => {
        if (listType !== type) {
          closeList();
          html.push(`<${type}>`);
          listType = type;
        }
      };

      lines.forEach((rawLine) => {
        const line = rawLine.trim();
        if (!line) {
          closeParagraph();
          closeList();
          return;
        }

        const heading = line.match(/^(#{1,6})\s+(.+)$/);
        if (heading) {
          closeParagraph();
          closeList();
          const level = Math.min(heading[1].length, 4);
          html.push(`<h${level}>${this.renderInlineMarkdown(heading[2])}</h${level}>`);
          return;
        }

        const unordered = line.match(/^[-*+]\s+(.+)$/);
        if (unordered) {
          closeParagraph();
          openList("ul");
          html.push(`<li>${this.renderInlineMarkdown(unordered[1])}</li>`);
          return;
        }

        const ordered = line.match(/^\d+\.\s+(.+)$/);
        if (ordered) {
          closeParagraph();
          openList("ol");
          html.push(`<li>${this.renderInlineMarkdown(ordered[1])}</li>`);
          return;
        }

        closeList();
        paragraph.push(line);
      });

      closeParagraph();
      closeList();
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
    resolveDiffFields(beforeData, afterData, changedFields) {
      const directFields = changedFields
        .filter((field) => field && field !== "restore")
        .map((field) => this.canonicalField(field));
      const candidates = directFields.length > 0 && !changedFields.includes("restore")
        ? directFields
        : this.snapshotFieldOrder();

      return Array.from(new Set(candidates)).filter((field) => {
        return !this.isSameValue(
          this.getFieldValue(beforeData, field),
          this.getFieldValue(afterData, field)
        );
      });
    },
    snapshotFieldOrder() {
      return [
        "agentCode",
        "agentName",
        "asrModelId",
        "vadModelId",
        "llmModelId",
        "slmModelId",
        "vllmModelId",
        "ttsModelId",
        "ttsVoiceId",
        "ttsLanguage",
        "ttsVolume",
        "ttsRate",
        "ttsPitch",
        "memModelId",
        "intentModelId",
        "chatHistoryConf",
        "systemPrompt",
        "summaryMemory",
        "langCode",
        "language",
        "sort",
        "functions",
        "contextProviders",
        "correctWordFileIds",
        "tagNames",
        "tagIds"
      ];
    },
    canonicalField(field) {
      return field === "tags" ? "tagNames" : field;
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
        return CHAT_HISTORY_CONF_LABELS[value] || CHAT_HISTORY_CONF_LABELS[Number(value)] || this.formatValue(value);
      }
      return this.formatValue(value);
    },
    modelDisplayName(value) {
      if (value === null || value === undefined || value === "") {
        return this.$t("agentSnapshot.emptyValue");
      }
      return this.modelNameMap[value] || FALLBACK_MODEL_NAMES[value] || String(value);
    },
    voiceDisplayName(modelId, value) {
      if (value === null || value === undefined || value === "") {
        return this.$t("agentSnapshot.emptyValue");
      }
      return this.voiceNameMap[`${modelId}:${value}`] || this.voiceNameMap[value] || String(value);
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
