<template>
  <div class="welcome">
    <HeaderBar />
    <div class="operation-bar">
      <h2 class="page-title">知识库中心</h2>
      <div class="right-operations">
        <el-input
          placeholder="搜索知识库..."
          v-model="searchKbName"
          class="search-input"
          @keyup.enter.native="handleSearchKb"
          clearable
          prefix-icon="el-icon-search"
        />
        <el-button class="btn-upload" @click="handleSearchKb">
          <i class="el-icon-search"></i>
          查询
        </el-button>
        <el-button class="btn-new-kb" @click="showAddDialog">
          <i class="el-icon-plus"></i>
          新建知识库
        </el-button>
      </div>
    </div>

    <div class="main-wrapper">
      <div class="content-panel">
        <div class="content-area" v-loading="loading" element-loading-text="加载中...">
          <!-- Knowledge Base Cards Section -->
          <div class="kb-section">
            <div class="kb-section-header">
              <div class="kb-section-title">知识库切换</div>
            </div>
            <div class="kb-cards-wrapper">
              <div class="kb-arrow left" @click="scrollCards(-1)" v-if="filteredKnowledgeBases.length > 0">
                <i class="el-icon-arrow-left"></i>
              </div>
              <div class="kb-cards" ref="kbCards">
                <div
                  v-for="(kb, index) in filteredKnowledgeBases"
                  :key="kb.datasetId"
                  class="kb-card"
                  :class="{ active: selectedKb && selectedKb.datasetId === kb.datasetId }"
                  @click="selectKnowledgeBase(kb)"
                >
                  <div class="kb-card-actions-top">
                    <button class="kb-action-icon" title="编辑" @click.stop="editKnowledgeBase(kb)">
                      <i class="el-icon-edit"></i>
                    </button>
                    <button class="kb-action-icon delete" title="删除" @click.stop="deleteKnowledgeBase(kb)">
                      <i class="el-icon-delete"></i>
                    </button>
                  </div>
                  <div class="kb-card-top">
                    <div class="kb-card-icon" :class="getCardColorClass(index)">
                      <i class="el-icon-document"></i>
                    </div>
                    <div class="kb-card-info">
                      <div class="kb-card-name">{{ kb.name }}</div>
                      <div class="kb-card-bottom">
                        <div class="kb-card-meta">
                          <span>{{`文档&nbsp;&nbsp;${kb.documentCount || 0}` }}</span>
                          <el-divider direction="vertical" />
                          <span>{{ formatDate(kb.createdAt) }}</span>
                          <el-divider direction="vertical" />
                          <el-switch
                            v-model="kb.status"
                            :active-value="1"
                            :inactive-value="0"
                            active-color="#13ce66"
                            inactive-color="#ff4949"
                            @click.native.stop
                            @change="handleStatusChange(kb)"
                          ></el-switch>
                        </div>
                      </div>
                    </div>
                  </div>
                  <div class="kb-card-desc">{{ kb.description || '-' }}</div>
                </div>
                <div v-if="filteredKnowledgeBases.length === 0 && !loading" class="kb-empty">
                  <i class="el-icon-folder-opened"></i>
                  <p>暂无知识库</p>
                </div>
              </div>
              <div class="kb-arrow right" @click="scrollCards(1)" v-if="filteredKnowledgeBases.length > 0">
                <i class="el-icon-arrow-right"></i>
              </div>
            </div>
          </div>

          <!-- Document Section -->
          <KnowledgeBaseItem
            ref="knowledgeBaseItem"
            v-if="selectedKb"
            :kb="selectedKb"
            @upload="showUploadDialog"
            @retrieval-test="showRetrievalTestDialog"
            @view-slices="handleViewSlices"
            @refresh="refreshDocuments"
          />
          <div v-else class="doc-empty-placeholder">
            <el-empty description="请先选择一个知识库"></el-empty>
          </div>
        </div>
      </div>
    </div>

    <!-- Knowledge Base Dialog -->
    <knowledge-base-dialog
      ref="knowledgeBaseDialog"
      :title="dialogTitle"
      :visible.sync="dialogVisible"
      :form="knowledgeBaseForm"
      @submit="handleSubmit"
      @cancel="dialogVisible = false"
    />

    <!-- Slice Dialog -->
    <el-dialog
      :title="`切片管理 - ${currentDocumentName}`"
      :visible.sync="sliceDialogVisible"
      width="900px"
      :close-on-click-modal="false"
    >
      <div class="slice-management">
        <div v-loading="sliceLoading" class="slice-content-container">
          <div v-if="sliceList.length > 0" class="slice-cards-container">
            <div v-for="(slice, index) in sliceList" :key="index" class="slice-card">
              <div class="slice-header-info">
                <p><strong>切片 {{ (sliceCurrentPage - 1) * slicePageSize + index + 1 }}</strong></p>
              </div>
              <div class="slice-card-content">
                <div class="content-text">{{ slice.content }}</div>
              </div>
            </div>
          </div>
          <div v-else class="no-slice-data">
            <el-empty description="暂无切片数据"></el-empty>
          </div>
        </div>
        <div class="slice-pagination">
          <el-select v-model="slicePageSize" @change="handleSliceSizeChange" class="slice-page-size-select">
            <el-option v-for="item in [10, 20, 50]" :key="item" :label="`${item}条/页`" :value="item"></el-option>
          </el-select>
          <button class="slice-page-btn" :disabled="sliceCurrentPage === 1" @click="sliceCurrentPage = 1; fetchSlices()">首页</button>
          <button class="slice-page-btn" :disabled="sliceCurrentPage === 1" @click="sliceCurrentPage--; fetchSlices()">上一页</button>
          <button v-for="page in sliceVisiblePages" :key="page" class="slice-page-btn" :class="{ active: page === sliceCurrentPage }" @click="sliceCurrentPage = page; fetchSlices()">{{ page }}</button>
          <button class="slice-page-btn" :disabled="sliceCurrentPage >= slicePageCount" @click="sliceCurrentPage++; fetchSlices()">下一页</button>
          <span class="slice-total-text">共 {{ sliceTotal }} 条</span>
        </div>
      </div>
    </el-dialog>

    <!-- Upload Dialog -->
    <el-dialog
      title="上传文档"
      :visible.sync="uploadDialogVisible"
      width="800px"
      :close-on-click-modal="false"
      @close="handleUploadDialogClose"
    >
      <el-upload
        ref="uploadRef"
        action="#"
        :auto-upload="false"
        :on-change="handleFileChange"
        multiple
        accept=".doc,.docx,.pdf,.txt,.md,.mdx,.csv,.xls,.xlsx,.ppt,.pptx"
        drag
      >
        <i class="el-icon-upload"></i>
        <div class="el-upload__text">将文件拖到此处，或点击上传</div>
        <div class="el-upload__tip" slot="tip">支持的文档类型：PDF、DOC、DOCX、TXT、MD、CSV、XLS、XLSX、PPT、PPTX，单次批量上传文件数不超过 32 个</div>
      </el-upload>
      <!-- 已选择文件列表 -->
      <div class="selected-files-section" v-if="selectedFilesList.length > 0">
        <h4>已选择文件 ({{ selectedFilesList.length }})</h4>
        <div class="selected-files-list">
          <div v-for="(file, index) in selectedFilesList" :key="index" class="selected-file-item">
            <div class="file-info">
              <i class="el-icon-document"></i>
              <span class="file-name">{{ file.name }}</span>
              <span class="file-size">{{ formatFileSize(file.size) }}</span>
            </div>
            <el-button type="text" class="remove-btn" @click="removeSelectedFile(index)">
              <i class="el-icon-close"></i>
            </el-button>
          </div>
        </div>
      </div>
      <span slot="footer">
        <el-button @click="uploadDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleBatchUploadSubmit" :loading="uploading" :disabled="selectedFilesList.length === 0">
          确认上传 ({{ selectedFilesList.length }})
        </el-button>
      </span>
    </el-dialog>

    <!-- Retrieval Test Dialog -->
    <el-dialog
      title="召回测试"
      :visible.sync="retrievalTestDialogVisible"
      width="900px"
      :close-on-click-modal="false"
    >
      <div class="retrieval-test-form">
        <el-form :model="retrievalTestForm" label-width="100px">
          <el-form-item label="测试问题" required>
            <el-input
              v-model="retrievalTestForm.question"
              type="textarea"
              :rows="3"
              placeholder="请输入测试问题"
            />
          </el-form-item>
        </el-form>
        <div style="text-align: center; margin-top: 20px;">
          <el-button type="primary" @click="runRetrievalTest" :loading="retrievalTestLoading">执行测试</el-button>
          <el-button @click="retrievalTestDialogVisible = false">取消</el-button>
        </div>
        <div v-if="retrievalTestResult" class="retrieval-test-result" style="margin-top: 20px;">
          <h4 style="margin-bottom: 12px;">测试结果</h4>
          <div class="result-chunks">
            <div v-for="(chunk, index) in retrievalTestResult.chunks" :key="index" class="result-chunk">
              <p><strong>切片 {{ index + 1 }}</strong></p>
              <div style="margin: 8px 0; font-size: 12px; color: #409eff;">相似度: {{ (chunk.similarity || 0).toFixed(4) }}</div>
              <div class="chunk-content">{{ chunk.content }}</div>
            </div>
          </div>
        </div>
      </div>
    </el-dialog>

    <el-footer>
      <version-footer />
    </el-footer>
  </div>
</template>

<script>
import Api from "@/apis/api";
import HeaderBar from "@/components/HeaderBar.vue";
import VersionFooter from "@/components/VersionFooter.vue";
import KnowledgeBaseDialog from "@/components/KnowledgeBaseDialog.vue";
import KnowledgeBaseItem from "./KnowledgeBaseItem.vue";

export default {
  components: { HeaderBar, VersionFooter, KnowledgeBaseDialog, KnowledgeBaseItem },
  data() {
    return {
      knowledgeBases: [],
      selectedKb: null,
      searchKbName: '',
      loading: false,
      dialogVisible: false,
      dialogTitle: '',
      knowledgeBaseForm: {
        id: null,
        datasetId: null,
        name: '',
        description: '',
        status: 1
      },
      uploadDialogVisible: false,
      sliceDialogVisible: false,
      retrievalTestDialogVisible: false,
      retrievalTestForm: {
        question: ''
      },
      retrievalTestResult: null,
      retrievalTestLoading: false,
      selectedFilesList: [],
      uploading: false,
      currentDocumentId: '',
      currentDocumentName: '',
      sliceList: [],
      sliceLoading: false,
      sliceCurrentPage: 1,
      slicePageSize: 10,
      sliceTotal: 0,
    };
  },
  computed: {
    filteredKnowledgeBases() {
      if (!this.searchKbName) return this.knowledgeBases;
      const keyword = this.searchKbName.toLowerCase();
      return this.knowledgeBases.filter(kb =>
        kb.name.toLowerCase().includes(keyword)
      );
    },
    slicePageCount() {
      return Math.ceil(this.sliceTotal / this.slicePageSize);
    },
    sliceVisiblePages() {
      const pages = [];
      const maxVisible = 3;
      let start = Math.max(1, this.sliceCurrentPage - 1);
      let end = Math.min(this.slicePageCount, start + maxVisible - 1);
      if (end - start + 1 < maxVisible) {
        start = Math.max(1, end - maxVisible + 1);
      }
      for (let i = start; i <= end; i++) {
        pages.push(i);
      }
      return pages;
    },
  },
  created() {
    this.fetchKnowledgeBases();
  },
  methods: {
    fetchKnowledgeBases() {
      this.loading = true;
      Api.knowledgeBase.getKnowledgeBaseList(
        { page: 1, page_size: 100, name: this.searchKbName },
        (res) => {
          this.loading = false;
          if (res.data && res.data.code === 0) {
            const pageData = res.data.data || {};
            this.knowledgeBases = pageData.list || [];
            if (this.knowledgeBases.length > 0 && !this.selectedKb) {
              this.selectKnowledgeBase(this.knowledgeBases[0]);
            } else if (this.selectedKb) {
              const updated = this.knowledgeBases.find(kb => kb.datasetId === this.selectedKb.datasetId);
              if (updated) this.selectedKb = updated;
            }
          } else {
            this.$message.error(res.data?.msg || '获取知识库列表失败');
          }
        },
        () => {
          this.loading = false;
          this.$message.error('获取知识库列表失败');
        }
      );
    },

    selectKnowledgeBase(kb) {
      this.selectedKb = kb;
    },

    refreshDocuments() {
      this.$refs.knowledgeBaseItem?.fetchDocuments();
    },

    handleSearchKb() {
      this.fetchKnowledgeBases();
    },

    scrollCards(direction) {
      const container = this.$refs.kbCards;
      if (container) {
        container.scrollBy({ left: direction * 364, behavior: 'smooth' });
      }
    },

    showAddDialog() {
      this.dialogTitle = '新增知识库';
      this.knowledgeBaseForm = {
        id: null,
        datasetId: null,
        name: '',
        description: '',
        status: 1
      };
      this.dialogVisible = true;
    },

    editKnowledgeBase(kb) {
      this.dialogTitle = '编辑知识库';
      this.knowledgeBaseForm = {
        id: kb.id,
        datasetId: kb.datasetId,
        name: kb.name,
        description: kb.description || '',
        status: kb.status,
        ragModelId: kb.ragModelId
      };
      this.dialogVisible = true;
    },

    handleStatusChange(kb) {
      const updateForm = {
        id: kb.id,
        datasetId: kb.datasetId,
        name: kb.name,
        description: kb.description,
        status: kb.status
      };
      Api.knowledgeBase.updateKnowledgeBase(kb.datasetId, updateForm, (res) => {
        if (res.data && res.data.code !== 0) {
          this.fetchKnowledgeBases();
          this.$message.error(res.data?.msg || '更新失败');
        } else {
          this.$message.success(kb.status === 1 ? '已启用' : '已停用');
          if (this.selectedKb && this.selectedKb.datasetId === kb.datasetId) {
            this.selectedKb = { ...kb };
          }
        }
      }, () => {
        this.fetchKnowledgeBases();
        this.$message.error('更新失败');
      });
    },

    deleteKnowledgeBase(kb) {
      this.$confirm(
        `确定要删除知识库「${kb.name}」吗？删除后不可恢复。`,
        '警告',
        {
          confirmButtonText: '确定',
          cancelButtonText: '取消',
          type: 'warning'
        }
      ).then(() => {
        Api.knowledgeBase.deleteKnowledgeBase(kb.datasetId, (res) => {
          if (res.data && res.data.code === 0) {
            this.$message.success('删除成功');
            if (this.selectedKb && this.selectedKb.datasetId === kb.datasetId) {
              this.selectedKb = null;
            }
            this.fetchKnowledgeBases();
          } else {
            this.$message.error(res.data?.msg || '删除失败');
          }
        }, (err) => {
          this.$message.error(err?.data?.msg || '删除失败');
        });
      }).catch(() => {});
    },

    showUploadDialog() {
      if (!this.selectedKb) {
        this.$message.warning('请先选择知识库');
        return;
      }
      this.uploadDialogVisible = true;
    },

    handleSubmit(form) {
      if (form.id) {
        Api.knowledgeBase.updateKnowledgeBase(form.datasetId, form, (res) => {
          if (res.data && res.data.code === 0) {
            this.dialogVisible = false;
            this.fetchKnowledgeBases();
            this.$message.success('修改成功');
          } else {
            this.$message.error(res.data?.msg || '更新失败');
          }
        }, (err) => {
          this.$message.error(err?.data?.msg || '更新失败');
        });
      } else {
        const createData = {
          name: form.name,
          description: form.description,
          status: form.status,
          ragModelId: form.ragModelId
        };
        Api.knowledgeBase.createKnowledgeBase(createData, (res) => {
          if (res.data && res.data.code === 0) {
            this.dialogVisible = false;
            this.fetchKnowledgeBases();
            this.$message.success('新增成功');
          } else {
            this.$message.error(res.data?.msg || '新增失败');
          }
        }, (err) => {
          this.$message.error(err?.data?.msg || '新增失败');
        });
      }
    },

    handleUploadDialogClose() {
      if (this.$refs.uploadRef) {
        this.$refs.uploadRef.clearFiles();
      }
      this.selectedFilesList = [];
    },

    handleFileChange(file, fileList) {
      if (!file || !file.raw) return;
      const isLt10M = file.size / 1024 / 1024 < 10;
      if (!isLt10M) {
        this.$message.error('文件大小不能超过10MB!');
        return;
      }
      this.selectedFilesList.push({
        name: file.name,
        size: file.size,
        raw: file.raw
      });
    },

    removeSelectedFile(index) {
      this.selectedFilesList.splice(index, 1);
    },

    formatFileSize(bytes) {
      if (bytes === 0) return '0 B';
      const k = 1024;
      const sizes = ['B', 'KB', 'MB', 'GB'];
      const i = Math.floor(Math.log(bytes) / Math.log(k));
      return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    },

    handleBatchUploadSubmit() {
      if (this.selectedFilesList.length === 0) {
        this.$message.error('请选择要上传的文件');
        return;
      }

      this.uploading = true;

      const uploadPromises = this.selectedFilesList.map(file => {
        return new Promise((resolve, reject) => {
          const formData = new FormData();
          formData.append('file', file.raw);

          Api.knowledgeBase.uploadDocument(this.selectedKb.datasetId, formData,
            ({ data }) => {
              if (data && data.code === 0) {
                resolve({ success: true, fileName: file.name });
              } else {
                reject({ success: false, fileName: file.name, error: data?.msg || '上传失败' });
              }
            },
            (err) => {
              if (err && err.data) {
                reject({ success: false, fileName: file.name, error: err.data.msg || err.msg || '上传失败' });
              } else {
                reject({ success: false, fileName: file.name, error: '上传失败' });
              }
              console.error('上传文档失败:', err);
            }
          );
        });
      });

      Promise.all(uploadPromises.map(p => p.catch(e => e)))
        .then(results => {
          this.uploading = false;

          const successCount = results.filter(r => r.success).length;
          const failedCount = results.filter(r => !r.success).length;

          if (successCount > 0) {
            this.$message.success(`成功上传 ${successCount} 个文件`);
          }

          if (failedCount > 0) {
            const failedFiles = results.filter(r => !r.success).map(r => r.fileName);
            this.$message.error(`上传失败 ${failedCount} 个文件: ${failedFiles.join(', ')}`);
          }

          if (successCount > 0) {
            this.uploadDialogVisible = false;
            this.refreshDocuments();
          }
        })
        .catch(error => {
          this.uploading = false;
          this.$message.error('批量上传失败');
          console.error('批量上传失败:', error);
        });
    },

    showRetrievalTestDialog() {
      if (!this.selectedKb) {
        this.$message.warning('请先选择知识库');
        return;
      }
      this.retrievalTestForm.question = '';
      this.retrievalTestResult = null;
      this.retrievalTestDialogVisible = true;
    },

    runRetrievalTest() {
      if (!this.retrievalTestForm.question.trim()) {
        this.$message.error('请输入测试问题');
        return;
      }
      this.retrievalTestLoading = true;
      Api.knowledgeBase.retrievalTest(
        this.selectedKb.datasetId,
        { question: this.retrievalTestForm.question.trim() },
        ({ data }) => {
          this.retrievalTestLoading = false;
          if (data && data.code === 0) {
            this.retrievalTestResult = data.data || data;
          } else {
            this.$message.error(data?.msg || '召回测试失败');
          }
        },
        (err) => {
          this.retrievalTestLoading = false;
          this.$message.error(err?.data?.msg || '召回测试失败');
        }
      );
    },

    handleViewSlices(doc) {
      this.currentDocumentId = doc.id;
      this.currentDocumentName = doc.name;
      this.sliceDialogVisible = true;
      this.sliceCurrentPage = 1;
      this.fetchSlices();
    },

    fetchSlices() {
      if (!this.selectedKb || !this.currentDocumentId) return;
      this.sliceLoading = true;
      const params = {
        page: this.sliceCurrentPage,
        page_size: this.slicePageSize
      };
      Api.knowledgeBase.listChunks(
        this.selectedKb.datasetId,
        this.currentDocumentId,
        params,
        ({ data }) => {
          this.sliceLoading = false;
          if (data && data.code === 0) {
            const responseData = data.data;
            if (responseData && responseData.list) {
              this.sliceList = responseData.list;
              this.sliceTotal = responseData.total || responseData.list.length;
            } else if (responseData && responseData.chunks && Array.isArray(responseData.chunks)) {
              this.sliceList = responseData.chunks;
              this.sliceTotal = responseData.total || responseData.chunks.length;
            } else if (Array.isArray(responseData)) {
              this.sliceList = responseData;
              this.sliceTotal = responseData.length;
            } else {
              this.sliceList = [];
              this.sliceTotal = 0;
            }
          } else {
            this.$message.error(data?.msg || '获取切片列表失败');
            this.sliceList = [];
            this.sliceTotal = 0;
          }
        },
        (err) => {
          this.sliceLoading = false;
          if (err && err.data) {
            this.$message.error(err.data.msg || err.msg || '获取切片列表失败');
          } else {
            this.$message.error('获取切片列表失败');
          }
          this.sliceList = [];
          this.sliceTotal = 0;
        }
      );
    },

    handleSliceSizeChange(val) {
      this.slicePageSize = val;
      this.sliceCurrentPage = 1;
      this.fetchSlices();
    },

    getCardColorClass(index) {
      const colors = ['blue', 'purple', 'green', 'orange'];
      return colors[index % colors.length];
    },

    getStatusClass(kb) {
      return kb.status === 1 ? 'active' : 'inactive';
    },

    getStatusText(kb) {
      return kb.status === 1 ? '已启用' : '未启用';
    },

    formatDate(dateString) {
      if (!dateString) return '';
      const date = new Date(dateString);
      return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
    },

    formatFileSize(bytes) {
      if (!bytes) return '0 B';
      const units = ['B', 'KB', 'MB', 'GB'];
      let i = 0;
      let size = bytes;
      while (size >= 1024 && i < units.length - 1) {
        size /= 1024;
        i++;
      }
      return size.toFixed(1) + ' ' + units[i];
    },
  }
};
</script>

<style lang="scss" scoped>
.welcome {
  min-width: 900px;
  min-height: 506px;
  height: 100vh;
  display: flex;
  position: relative;
  flex-direction: column;
  background: linear-gradient(to bottom right, #dce8ff, #e4eeff, #e6cbfd) center;
  background-size: cover;
  -webkit-background-size: cover;
  -o-background-size: cover;
  overflow: hidden;
}

.main-wrapper {
  height: calc(100vh - 63px - 35px - 72px);
  margin: 0 22px;
  position: relative;
  display: flex;
  flex-direction: column;
}

.operation-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px;
}

.page-title {
  font-size: 24px;
  margin: 0;
}

.right-operations {
  display: flex;
  gap: 10px;
  margin-left: auto;
  align-items: center;
}

.search-input {
  width: 240px;
}

.btn-upload {
  height: 40px;
  padding: 0 20px;
  border: 1px solid #2f5bff !important;
  border-radius: 8px;
  background: #fff;
  color: #2f5bff;
  font-size: 14px;
  font-weight: 500;
  transition: all 0.2s;

  &:hover {
    background: #f2f6ff;
  }
}

.btn-new-kb {
  height: 40px;
  padding: 0 20px;
  border: none !important;
  border-radius: 8px;
  background: linear-gradient(135deg, #6a5cff, #2f5bff) !important;
  color: #fff;
  font-size: 14px;
  font-weight: 500;
  transition: opacity 0.2s;

  &:hover {
    opacity: 0.9;
  }
}

.content-panel {
  flex: 1;
  display: flex;
  overflow: hidden;
  height: 100%;
  border-radius: 15px;
}

.content-area {
  flex: 1;
  height: 100%;
  min-width: 600px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* ========== Knowledge Base Cards Section ========== */
.kb-section {
  background: #fff;
  border-radius: 16px;
  padding: 14px 20px;
  box-shadow: 0 4px 16px rgba(31, 42, 68, 0.06);
  border: 1px solid #f0f3f9;
}

.kb-section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.kb-section-title {
  font-size: 20px;
  font-weight: 700;
  color: #1f2a44;
}

.kb-cards-wrapper {
  display: flex;
  align-items: center;
  gap: 12px;
}

.kb-cards {
  flex: 1;
  display: flex;
  gap: 24px;
  overflow-x: auto;
  padding: 10px;
  scroll-behavior: smooth;
  scrollbar-width: none;

  &::-webkit-scrollbar {
    display: none;
  }
}

.kb-arrow {
  width: 40px;
  height: 40px;
  flex-shrink: 0;
  border-radius: 50%;
  background: #fff;
  border: 1px solid #e7ecf5;
  box-shadow: 0 4px 16px rgba(31, 42, 68, 0.06);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.2s;
  color: #2f5bff;
  font-size: 18px;

  &:hover {
    border-color: #2f5bff;
    box-shadow: 0 4px 20px rgba(47, 91, 255, 0.15);
  }
}

.kb-card {
  width: 340px;
  border-radius: 8px;
  padding: 20px;
  border: 1px solid transparent;
  background: #fff;
  cursor: pointer;
  transition: all 0.25s;
  display: flex;
  flex-direction: column;
  flex: 0 0 340px;
  position: relative;
  box-shadow: 0 0 10px rgba(47, 91, 255, 0.15);

  &:hover {
    box-shadow: 0 0 10px rgba(47, 91, 255, 0.15);
    border: 1px solid #6b80eb;
  }

  &.active {
    border: 1px solid #6b80eb;
  }
}

.kb-card-top {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 12px;
}

.kb-card-actions-top {
  position: absolute;
  top: 10px;
  right: 4px;
  display: flex;
  z-index: 2;
}

.kb-action-icon {
  width: 24px;
  height: 24px;
  border-radius: 4px;
  border: none;
  background: transparent;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: #6b7280;
  font-size: 13px;
  transition: all 0.2s;
  padding: 0;

  &:hover {
    color: #2f5bff;
  }

  &.delete:hover {
    color: #ff5a5f;
  }
}

.kb-card-icon {
  width: 56px;
  height: 56px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  flex-shrink: 0;

  &.blue {
    background: linear-gradient(135deg, #e8ecff, #d4daff);
    color: #2f5bff;
  }
  &.purple {
    background: linear-gradient(135deg, #ede8ff, #dcd4ff);
    color: #6a5cff;
  }
  &.green {
    background: linear-gradient(135deg, #e2f9ed, #c8f0d8);
    color: #34c759;
  }
  &.orange {
    background: linear-gradient(135deg, #fff3e0, #ffe4b8);
    color: #ff9500;
  }
}

.kb-card-info {
  height: 100%;
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.kb-card-name {
  font-size: 18px;
  font-weight: 600;
  color: #1f2a44;
  margin-bottom: 6px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  text-align: left;
}

.kb-card-desc {
  margin-top: 10px;
  font-size: 14px;
  text-align: left;
  color: #7888a8;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.kb-card-bottom {
  margin-top: auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.kb-card-meta {
  font-size: 12px;
  color: #a0aec0;
}

.kb-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 120px;
  width: 100%;
  color: #b0bbc9;
  font-size: 14px;

  i {
    font-size: 36px;
    margin-bottom: 8px;
  }
}

/* ========== Slice Dialog ========== */
.slice-management {
  display: flex;
  flex-direction: column;
  max-height: 65vh;
}

.slice-content-container {
  flex: 1;
  overflow: hidden;
}

.slice-cards-container {
  max-height: 50vh;
  overflow-y: auto;
  padding-right: 4px;

  &::-webkit-scrollbar {
    width: 6px;
  }
  &::-webkit-scrollbar-thumb {
    background: #e0e0e0;
    border-radius: 3px;
  }
}

.slice-card {
  background: #f8f9fa;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 14px;
  margin-bottom: 12px;

  &:last-child {
    margin-bottom: 0;
  }
}

.slice-header-info {
  margin-bottom: 10px;
  p {
    margin: 0;
    font-size: 14px;
    strong {
      color: #374151;
    }
  }
}

.slice-card-content {
  background: #fff;
  border: 1px solid #f0f0f0;
  border-radius: 4px;
  padding: 12px;
  max-height: 200px;
  overflow-y: auto;

  &::-webkit-scrollbar {
    width: 4px;
  }
  &::-webkit-scrollbar-thumb {
    background: #e0e0e0;
    border-radius: 2px;
  }
}

.content-text {
  font-size: 14px;
  line-height: 1.6;
  color: #333;
  white-space: pre-wrap;
  word-break: break-word;
}

.no-slice-data {
  min-height: 200px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.slice-pagination {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid #e5e7eb;
}

.slice-page-size-select {
  width: 100px;
  margin-right: 8px;
}

.slice-page-btn {
  min-width: 32px;
  height: 28px;
  padding: 0 8px;
  border-radius: 4px;
  border: 1px solid #e5e7eb;
  background: #fff;
  color: #606266;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;

  &:hover {
    background: #f5f7fa;
  }

  &:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  &.active {
    background: #6b80eb;
    color: #fff;
    border-color: #6b80eb;
  }
}

.slice-total-text {
  margin-left: 8px;
  color: #9ca3af;
  font-size: 13px;
}

/* ========== Selected Files List ========== */
.selected-files-section {
  margin-top: 16px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 16px;
  background-color: #f8f9fa;

  h4 {
    margin: 0 0 12px 0;
    font-size: 14px;
    font-weight: 600;
    color: #606266;
  }
}

.selected-files-list {
  max-height: 180px;
  overflow-y: auto;
}

.selected-file-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background-color: white;
  border: 1px solid #e5e7eb;
  border-radius: 4px;
  margin-bottom: 8px;

  &:last-child {
    margin-bottom: 0;
  }

  .file-info {
    display: flex;
    align-items: center;
    flex: 1;

    .el-icon-document {
      color: #409eff;
      margin-right: 8px;
      font-size: 16px;
    }

    .file-name {
      font-size: 14px;
      color: #303133;
      margin-right: 12px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      max-width: 300px;
    }

    .file-size {
      font-size: 12px;
      color: #909399;
    }
  }

  .remove-btn {
    color: #f56c6c;
    padding: 4px;

    &:hover {
      color: #f78989;
      background-color: #fef0f0;
      border-radius: 4px;
    }
  }
}

/* ========== Retrieval Test Dialog ========== */
.retrieval-test-form {
  .result-chunks {
    max-height: 400px;
    overflow-y: auto;
  }

  .result-chunk {
    background: #f8f9fa;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 14px;
    margin-bottom: 12px;

    p {
      margin: 0 0 8px 0;
      font-size: 14px;
    }

    .chunk-content {
      background: #fff;
      border: 1px solid #f0f0f0;
      border-radius: 4px;
      padding: 12px;
      max-height: 150px;
      overflow-y: auto;
      font-size: 14px;
      line-height: 1.6;
      white-space: pre-wrap;
      word-break: break-word;
    }
  }
}
</style>
