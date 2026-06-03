<template>
  <div class="doc-section">
    <div class="doc-section-header">
      <div class="doc-section-left">
        <div class="doc-section-title">{{`当前知识库文档资产（${kb?.name}）`}}</div>
        <div class="doc-section-count" v-if="kb">共 {{ documents.length }} 个文档</div>
      </div>
      <div class="doc-section-actions">
        <el-input
          placeholder="搜索文档..."
          v-model="searchDocName"
          class="doc-search-input"
          size="small"
          prefix-icon="el-icon-search"
          clearable
        />
        <el-button size="small" @click="handleSearch">查询</el-button>
        <el-button size="small" @click="handleUpload">新增</el-button>
        <el-button size="small" @click="handleRetrievalTest">召回测试</el-button>
      </div>
    </div>
    <div class="doc-grid" v-loading="docLoading" element-loading-text="加载中...">
      <div v-for="doc in documents" :key="doc.id" class="doc-card">
        <div class="doc-card-top">
          <div class="doc-file-icon" :class="getFileIconClass(doc.name)">
            <i :class="getFileIcon(doc.name)"></i>
          </div>
          <div class="doc-card-info">
            <div class="doc-card-name" :title="doc.name">{{ doc.name }}</div>
            <div class="doc-card-meta">上传时间 {{ formatDate(doc.createdAt) }}</div>
          </div>
        </div>
        <div class="doc-card-bottom">
          <div class="doc-card-progress">
            <div class="progress-ring">
              <svg viewBox="0 0 36 36">
                <circle class="bg" cx="18" cy="18" r="14"/>
                <circle class="fg" :class="getProgressClass(doc)" cx="18" cy="18" r="14"
                  stroke-dasharray="87.96"
                  :stroke-dashoffset="getProgressOffset(doc)"/>
              </svg>
              <span class="progress-ring-text" :style="{ color: getProgressTextColor(doc) }">{{ getProgressText(doc) }}</span>
            </div>
            <span class="progress-label" :class="getProgressClass(doc)">{{ getDocStatusText(doc) }}</span>
            <span class="doc-slice-count" v-if="doc.sliceCount > 0">切片 {{ doc.sliceCount }}</span>
          </div>
          <div class="doc-card-actions">
            <el-button
              v-if="doc.parseStatusCode === 3"
              type="text"
              @click.stop="$emit('view-slices', doc)"
            >
              查看切片
            </el-button>
            <el-button
              v-else
              type="text"
              :disabled="doc.parseStatusCode === 1"
              :loading="doc.parsing"
              @click.stop="handleParse(doc)"
            >
              解析
            </el-button>
            <el-button type="text" class="delete-btn" @click.stop="handleDelete(doc)">
              删除
            </el-button>
          </div>
        </div>
      </div>
      <div v-if="documents.length === 0 && !docLoading" class="doc-empty">
        <el-empty description="暂无文档"></el-empty>
      </div>
    </div>
  </div>
</template>

<script>
import Api from "@/apis/api";

export default {
  name: 'LibraryItem',
  props: {
    kb: {
      type: Object,
      default: null
    }
  },
  data() {
    return {
      documents: [],
      docLoading: false,
      searchDocName: '',
    };
  },
  watch: {
    kb: {
      handler(newKb) {
        if (newKb && newKb.datasetId) {
          this.fetchDocuments();
        } else {
          this.documents = [];
        }
      },
      immediate: true
    }
  },
  methods: {
    fetchDocuments() {
      if (!this.kb || !this.kb.datasetId) return;
      this.docLoading = true;
      const params = {
        page: 1,
        page_size: 100,
        name: this.searchDocName
      };
      Api.knowledgeBase.getDocumentList(
        this.kb.datasetId,
        params,
        ({ data }) => {
          this.docLoading = false;
          if (data && data.code === 0) {
            this.documents = data.data.list || [];
            this.fetchSliceCountsForDocuments();
          } else {
            this.$message.error(data?.msg || '获取文档列表失败');
            this.documents = [];
          }
        },
        (err) => {
          this.docLoading = false;
          if (err && err.data) {
            this.$message.error(err.data.msg || err.msg || '获取文档列表失败');
          } else {
            this.$message.error('获取文档列表失败');
          }
          this.documents = [];
        }
      );
    },

    handleSearch() {
      this.fetchDocuments();
    },

    handleUpload() {
      if (!this.kb) {
        this.$message.warning('请先选择知识库');
        return;
      }
      this.$emit('upload');
    },

    handleRetrievalTest() {
      if (!this.kb) {
        this.$message.warning('请先选择知识库');
        return;
      }
      this.$emit('retrieval-test');
    },

    handleDelete(doc) {
      if (!this.kb) return;
      this.$confirm(
        '确定要删除该文档吗？',
        '警告',
        {
          confirmButtonText: '确定',
          cancelButtonText: '取消',
          type: 'warning'
        }
      ).then(() => {
        Api.knowledgeBase.deleteDocument(this.kb.datasetId, doc.id, (res) => {
          if (res.data && res.data.code === 0) {
            this.fetchDocuments();
            this.$message.success('文档删除成功');
          } else {
            this.$message.error(res.data?.msg || '文档删除失败');
          }
        }, () => {
          this.$message.error('文档删除失败');
        });
      }).catch(() => {});
    },

    handleParse(doc) {
      this.$confirm('确定要解析该文档吗？', '提示', {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'info'
      }).then(() => {
        this.$set(doc, 'parsing', true);
        doc.parseStatusCode = 1;
        Api.knowledgeBase.parseDocument(
          this.kb.datasetId,
          doc.id,
          ({ data }) => {
            if (data && data.code === 0) {
              this.$message.success('解析请求已提交，正在处理中');
              this.$set(doc, 'parsing', false);
              this.startParsePolling(doc);
            } else {
              this.$set(doc, 'parsing', false);
              doc.parseStatusCode = 0;
              this.$message.error(data?.msg || '解析失败');
            }
          },
          (err) => {
            this.$set(doc, 'parsing', false);
            doc.parseStatusCode = 0;
            this.$message.error(err?.data?.msg || '解析失败');
          }
        );
      }).catch(() => {});
    },

    startParsePolling(doc) {
      const poll = () => {
        if (!this.kb) return;
        Api.knowledgeBase.getDocumentList(
          this.kb.datasetId,
          { page: 1, page_size: 100, name: this.searchDocName },
          ({ data }) => {
            if (data && data.code === 0) {
              const list = data.data.list || [];
              const updated = list.find(d => d.id === doc.id);
              if (updated) {
                this.$set(doc, 'parseStatusCode', updated.parseStatusCode);
                if (updated.parseStatusCode !== 1) {
                  this.$set(doc, 'parsing', false);
                  if (updated.parseStatusCode === 3) {
                    this.$message.success(`文档「${doc.name}」解析完成`);
                    this.fetchSliceCountForSingleDocument(doc);
                  } else if (updated.parseStatusCode === 4) {
                    this.$message.error(`文档「${doc.name}」解析失败`);
                  }
                  return;
                }
              }
              setTimeout(poll, 5000);
            }
          },
          () => {
            setTimeout(poll, 5000);
          }
        );
      };
      setTimeout(poll, 3000);
    },

    fetchSliceCountsForDocuments() {
      if (!this.documents || this.documents.length === 0) return;
      this.documents.forEach(doc => {
        this.fetchSliceCountForSingleDocument(doc);
      });
    },

    fetchSliceCountForSingleDocument(doc) {
      const params = { page: 1, page_size: 1 };
      Api.knowledgeBase.listChunks(
        this.kb.datasetId,
        doc.id,
        params,
        ({ data }) => {
          if (data && data.code === 0) {
            this.$set(doc, 'sliceCount', data.data.total || 0);
          }
        },
        () => {}
      );
    },

    getFileIconClass(fileName) {
      if (!fileName) return 'txt';
      const ext = fileName.split('.').pop().toLowerCase();
      if (ext === 'pdf') return 'pdf';
      if (['doc', 'docx'].includes(ext)) return 'word';
      if (['xls', 'xlsx', 'csv'].includes(ext)) return 'excel';
      if (['ppt', 'pptx'].includes(ext)) return 'ppt';
      if (['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'].includes(ext)) return 'img';
      return 'txt';
    },

    getFileIcon(fileName) {
      if (!fileName) return 'el-icon-document';
      const ext = fileName.split('.').pop().toLowerCase();
      if (ext === 'pdf') return 'el-icon-document';
      if (['doc', 'docx'].includes(ext)) return 'el-icon-document';
      if (['xls', 'xlsx', 'csv'].includes(ext)) return 'el-icon-s-grid';
      if (['ppt', 'pptx'].includes(ext)) return 'el-icon-data-board';
      if (['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'].includes(ext)) return 'el-icon-picture';
      return 'el-icon-document';
    },

    getProgressClass(doc) {
      const code = doc.parseStatusCode;
      if (code === 3) return 'complete';
      if (code === 1) return 'processing';
      return 'pending';
    },

    getProgressOffset(doc) {
      const code = doc.parseStatusCode;
      const circumference = 87.96;
      if (code === 3) return 0;
      if (code === 1) {
        const progress = doc.chunkNum && doc.totalChunkNum
          ? Math.round((doc.chunkNum / doc.totalChunkNum) * 100)
          : 50;
        return circumference * (1 - progress / 100);
      }
      return circumference;
    },

    getProgressText(doc) {
      const code = doc.parseStatusCode;
      if (code === 3) return '✓';
      if (code === 1) {
        if (doc.chunkNum && doc.totalChunkNum) {
          return Math.round((doc.chunkNum / doc.totalChunkNum) * 100) + '%';
        }
        return '50%';
      }
      return '0%';
    },

    getProgressTextColor(doc) {
      const code = doc.parseStatusCode;
      if (code === 3) return '#34c759';
      if (code === 1) return '#2f5bff';
      return '#7888a8';
    },

    getDocStatusText(doc) {
      const code = doc.parseStatusCode;
      if (code === 3) return '已完成';
      if (code === 1) return '处理中';
      if (code === 0) return '未开始';
      if (code === 4) return '失败';
      if (code === 2) return '已取消';
      return '未开始';
    },

    formatDate(dateString) {
      if (!dateString) return '';
      const date = new Date(dateString);
      return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
    },
  }
};
</script>

<style lang="scss" scoped>
/* ========== Document Section ========== */
.doc-section {
  background: #fff;
  border-radius: 16px;
  padding: 16px 20px;
  box-shadow: 0 4px 16px rgba(31, 42, 68, 0.06);
  border: 1px solid #f0f3f9;
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.doc-section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.doc-section-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.doc-section-title {
  font-size: 20px;
  font-weight: 700;
  color: #1f2a44;
}

.doc-section-count {
  font-size: 14px;
  color: #788ba8;
}

.doc-section-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.doc-search-input {
  width: 200px;
  margin-left: 8px;
}

/* ========== Document Grid ========== */
.doc-grid {
  padding: 10px;
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px 20px;
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  scrollbar-width: thin;
}

.doc-card {
  height: 110px;
  border-radius: 8px;
  border: 1px solid transparent;
  padding: 18px;
  background: #fff;
  display: flex;
  flex-direction: column;
  cursor: pointer;
  transition: all 0.25s;
  position: relative;
  box-shadow: 0 0 6px rgba(47, 91, 255, 0.15);

  &:hover {
    box-shadow: 0 0 6px rgba(47, 91, 255, 0.15);
    border: 1px solid #6b80eb;
  }
}

.doc-card-top {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 12px;
}

.doc-file-icon {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  flex-shrink: 0;

  &.pdf { background: #fff0f0; color: #ff5a5f; }
  &.word { background: #e8ecff; color: #2f5bff; }
  &.excel { background: #e8f9ee; color: #34c759; }
  &.ppt { background: #fff3e0; color: #ff9500; }
  &.txt { background: #f0f3f9; color: #788ba8; }
  &.img { background: #f3e8ff; color: #9b59b6; }
}

.doc-card-info {
  flex: 1;
  min-width: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
  justify-content: space-around;
  text-align: left;
}

.doc-card-name {
  font-size: 15px;
  font-weight: 600;
  color: #1f2a44;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 4px;
}

.doc-card-meta {
  font-size: 13px;
  color: #7888a8;
}

.doc-card-bottom {
  margin-top: auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.doc-card-progress {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* ========== Progress Ring ========== */
.progress-ring {
  width: 36px;
  height: 36px;
  position: relative;

  svg {
    width: 36px;
    height: 36px;
    transform: rotate(-90deg);
  }

  .bg {
    fill: none;
    stroke: #e7ecf5;
    stroke-width: 4;
  }

  .fg {
    fill: none;
    stroke-width: 4;
    stroke-linecap: round;
    transition: stroke-dashoffset 0.5s ease;

    &.complete { stroke: #34c759; }
    &.processing { stroke: #2f5bff; }
    &.pending { stroke: #e7ecf5; }
  }
}

.progress-ring-text {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  font-size: 10px;
  font-weight: 600;
  color: #7888a8;
}

.progress-label {
  font-size: 12px;
  color: #7888a8;

  &.complete { color: #34c759; }
  &.processing { color: #2f5bff; }
}

.doc-card-actions {
  display: flex;
  align-items: center;
  gap: 4px;

  :deep(.el-button--text) {
    padding: 4px 8px;
    font-size: 13px;
  }

  .delete-btn {
    color: #f56c6c !important;
    &:hover {
      color: #f78989 !important;
    }
  }
}

.doc-slice-count {
  font-size: 12px;
  color: #6b80eb;
  background: #f0f3ff;
  padding: 2px 8px;
  border-radius: 4px;
  margin-left: 4px;
}

.doc-empty {
  grid-column: 1 / -1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 300px;
  color: #b0bbc9;
  font-size: 14px;

  i {
    font-size: 48px;
    margin-bottom: 12px;
  }
}

@media (max-width: 1144px) {
  .doc-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 900px) {
  .doc-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>