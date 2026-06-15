<template>
  <div class="welcome">
    <HeaderBar />
    <div class="main-wrapper">
      <div class="content-panel">
        <div class="content-area">
          <el-card class="params-card" shadow="never">
            <div class="operation-header">
              <h2 class="page-title">{{ $t('paramManagement.pageTitle') }}</h2>
              <div class="right-operations">
                <el-input :placeholder="$t('paramManagement.searchPlaceholder')" v-model="searchCode" class="search-input"
                  @keyup.enter.native="handleSearch" clearable />
                <CustomButton icon="el-icon-search" type="confirm" @click="handleSearch">{{ $t('paramManagement.search') }}</CustomButton>
              </div>
            </div>
            <CustomTable
              ref="paramsTable"
              :data="paramsList"
              :columns="tableColumns"
              :loading="loading"
              :show-selection="true"
              :show-operations="true"
              :operations-label="$t('paramManagement.operation')"
              :total="total"
              :current-page="currentPage"
              :page-size="pageSize"
              :page-size-options="pageSizeOptions"
              :hide-text="$t('paramManagement.hide')"
              :view-text="$t('paramManagement.view')"
              @size-change="handlePageSizeChange"
              @page-change="goToPage"
            >
              <!-- 选择列自定义插槽 -->
              <template slot="selection" slot-scope="scope">
                <el-checkbox v-model="scope.row.selected"></el-checkbox>
              </template>
              <template slot="paramValue" slot-scope="scope">
                <div v-if="isSensitiveParam(scope.row.paramCode)">
                  <span v-if="!scope.row.showValue">
                    {{ maskSensitiveValue(scope.row.paramValue) }}
                  </span>
                  <span v-else>{{ scope.row.paramValue }}</span>
                  <el-button size="mini" type="text" @click="toggleSensitiveValue(scope.row)">
                    {{ scope.row.showValue ? $t('paramManagement.hide') : $t('paramManagement.view') }}
                  </el-button>
                </div>
                <span v-else>{{ scope.row.paramValue }}</span>
              </template>
              <!-- 操作列插槽 -->
              <template slot="operations" slot-scope="scope">
                <el-button size="mini" type="text" @click="editParam(scope.row)">
                  {{ $t('paramManagement.edit') }}
                </el-button>
                <el-button size="mini" type="text" @click="deleteParam(scope.row)">
                  {{ $t('paramManagement.delete') }}
                </el-button>
              </template>
              <template slot="footer-btns">
                <div class="ctrl_btn">
                  <CustomButton :icon="isAllSelected ? 'el-icon-circle-close' : 'el-icon-circle-check'" size="small" @click="handleSelectAll">
                    {{ isAllSelected ? $t('paramManagement.deselectAll') : $t('paramManagement.selectAll') }}
                  </CustomButton>
                  <CustomButton icon="el-icon-plus" size="small" @click="showAddDialog">
                    {{ $t('paramManagement.add') }}
                  </CustomButton>
                  <CustomButton size="small" type="delete" icon="el-icon-delete" @click="deleteSelectedParams">
                    {{ $t('paramManagement.delete') }}
                  </CustomButton>
                </div>
              </template>
            </CustomTable>
          </el-card>
        </div>
      </div>
    </div>

    <!-- 新增/编辑参数对话框 -->
    <param-dialog
      ref="paramDialog"
      :title="dialogTitle"
      :visible.sync="dialogVisible"
      :form="paramForm"
      @submit="handleSubmit"
      @cancel="dialogVisible = false"
    />
    <el-footer>
      <version-footer />
    </el-footer>
  </div>
</template>

<script>
import Api from "@/apis/api";
import HeaderBar from "@/components/HeaderBar.vue";
import ParamDialog from "@/components/ParamDialog.vue";
import VersionFooter from "@/components/VersionFooter.vue";
import CustomButton from "@/components/CustomButton.vue";
import CustomTable from "@/components/CustomTable.vue";
import CustomDialog from "@/components/CustomDialog.vue";

export default {
  components: { HeaderBar, ParamDialog, VersionFooter, CustomButton, CustomTable, CustomDialog },
  data() {
    return {
      searchCode: "",
      paramsList: [],
      currentPage: 1,
      loading: false,
      pageSize: 10,
      pageSizeOptions: [10, 20, 50, 100],
      total: 0,
      dialogVisible: false,
      dialogTitle: "新增参数",
      isAllSelected: false,
      sensitive_keys: ["api_key", "personal_access_token", "access_token", "token", "secret", "access_key_secret", "secret_key", "password", "mqtt_signature_key", "private_key"],
      paramForm: {
        id: null,
        paramCode: "",
        paramValue: "",
        valueType: "string",
        remark: ""
      },
      tableColumns: []
    };
  },
  created() {
    this.initTableColumns();
    this.fetchParams();

  },

  computed: {
    pageCount() {
      return Math.ceil(this.total / this.pageSize);
    },
    visiblePages() {
      const pages = [];
      const maxVisible = 3;
      let start = Math.max(1, this.currentPage - 1);
      let end = Math.min(this.pageCount, start + maxVisible - 1);

      if (end - start + 1 < maxVisible) {
        start = Math.max(1, end - maxVisible + 1);
      }

      for (let i = start; i <= end; i++) {
        pages.push(i);
      }
      return pages;
    },
  },
  methods: {
    initTableColumns() {
      this.tableColumns = [
        {
          prop: 'paramCode',
          label: this.$t('paramManagement.paramCode'),
          align: 'center'
        },
        {
          prop: 'paramValue',
          label: this.$t('paramManagement.paramValue'),
          align: 'center',
          sensitive: true,
          toggleable: true
        },
        {
          prop: 'remark',
          label: this.$t('paramManagement.remark'),
          align: 'center'
        }
      ];
    },
    handlePageSizeChange(val) {
      this.pageSize = val;
      this.currentPage = 1;
      this.fetchParams();
    },
    fetchParams() {
      this.loading = true;
      Api.admin.getParamsList(
        {
          page: this.currentPage,
          limit: this.pageSize,
          paramCode: this.searchCode,
        },
        ({ data }) => {
          this.loading = false;
          if (data.code === 0) {
            this.paramsList = data.data.list.map(item => ({
              ...item,
              valueType: item.valueType || "string",
              selected: false,
              showValue: false
            }));
            this.total = data.data.total;
          } else {
            this.$message.error({
              message: data.msg || this.$t('paramManagement.getParamsListFailed'),
              showClose: true
            });
          }
        }
      );
    },
    handleSearch() {
      this.currentPage = 1;
      this.fetchParams();
    },
    handleSelectAll() {
      this.isAllSelected = !this.isAllSelected;
      this.paramsList.forEach(row => {
        row.selected = this.isAllSelected;
      });
    },
    showAddDialog() {
      this.dialogTitle = this.$t('paramManagement.addParam');
      this.paramForm = {
        id: null,
        paramCode: "",
        paramValue: "",
        valueType: "string", // 默认值
        remark: ""
      };
      this.dialogVisible = true;
    },
    editParam(row) {
      this.dialogTitle = this.$t('paramManagement.editParam');
      this.paramForm = {
        id: row.id,
        paramCode: row.paramCode,
        paramValue: row.paramValue,
        valueType: row.valueType || "string", // 确保有值
        remark: row.remark
      };
      this.dialogVisible = true;
    },
    handleSubmit(form) {
      if (form.id) {
        // 更新参数
        Api.admin.updateParam(form, ({ data }) => {
          this.dialogVisible = false;
          this.fetchParams();
          this.$message.success({
            message: this.$t('paramManagement.updateSuccess'),
            showClose: true
          });
        }, ({ data }) => {
          this.$message.error({
            message: data.msg || this.$t('paramManagement.updateFailed'),
            showClose: true
          });
          // 调用ParamDialog的resetSaving方法重置保存状态
          if (this.$refs.paramDialog && typeof this.$refs.paramDialog.resetSaving === 'function') {
            this.$refs.paramDialog.resetSaving();
          }
        });
      } else {
        // 新增参数
        Api.admin.addParam(form, ({ data }) => {
          if (data.code === 0) {
            this.dialogVisible = false;
            this.fetchParams();
            this.$message.success({
              message: this.$t('paramManagement.addSuccess'),
              showClose: true
            });
          } else {
            this.$message.error({
              message: data.msg || this.$t('paramManagement.addFailed'),
              showClose: true
            });
            // 调用ParamDialog的resetSaving方法重置保存状态
            if (this.$refs.paramDialog && typeof this.$refs.paramDialog.resetSaving === 'function') {
              this.$refs.paramDialog.resetSaving();
            }
          }
        }, ({ data }) => {
          this.$message.error({
            message: data.msg || this.$t('paramManagement.updateFailed'),
            showClose: true
          });
          // 调用ParamDialog的resetSaving方法重置保存状态
          if (this.$refs.paramDialog && typeof this.$refs.paramDialog.resetSaving === 'function') {
            this.$refs.paramDialog.resetSaving();
          }
        });
      }
    },
    deleteSelectedParams() {
      const selectedParams = this.paramsList.filter(row => row.selected);
      if (selectedParams.length === 0) {
        this.$message.warning({
          message: this.$t('paramManagement.selectParamsFirst'),
          showClose: true
        });
        return;
      }
      this.deleteParams(selectedParams);
    },
    deleteParam(row) {
      if (!row.id) {
        this.$message.warning({
          message: this.$t('paramManagement.selectParamsFirst'),
          showClose: true
        });
        return;
      }
      this.deleteParams([row]);
    },
    deleteParams(params) {
      const paramCount = params.length;
      const paramIds = params.map(param => param.id).filter(id => id);
      if (paramIds.length === 0) {
        this.$message.error({
          message: this.$t('paramManagement.invalidParamId'),
          showClose: true
        });
        return;
      }
      this.$confirm(this.$t('paramManagement.confirmBatchDelete', { paramCount }), this.$t('message.warning'), {
        confirmButtonText: this.$t('button.ok'),
        cancelButtonText: this.$t('button.cancel'),
        type: 'warning'
      }).then(() => {
        Api.admin.deleteParam(paramIds, ({ data }) => {
          if (data.code === 0) {
            this.fetchParams();
            this.$message.success({
              message: this.$t('paramManagement.batchDeleteSuccess', { paramCount }),
              showClose: true
            });
          } else {
            this.$message.error({
              message: data.msg || this.$t('paramManagement.deleteFailed'),
              showClose: true
            });
          }
        });
      }).catch(() => {
        this.$message({
          type: 'info',
          message: this.$t('paramManagement.operationCancelled'),
          duration: 1000
        });
      });
    },
    goToPage(page) {
      if (page !== this.currentPage) {
        this.currentPage = page;
        this.fetchParams();
      }
    },
    goFirst() {
      if (this.currentPage !== 1) {
        this.currentPage = 1;
        this.fetchParams();
      }
    },
    goPrev() {
      if (this.currentPage > 1) {
        this.currentPage--;
        this.fetchParams();
      }
    },
    goNext() {
      if (this.currentPage < this.pageCount) {
        this.currentPage++;
        this.fetchParams();
      }
    },
    isSensitiveParam(paramCode) {
      return this.sensitive_keys.some(key => paramCode.toLowerCase().includes(key));
    },
    maskSensitiveValue(value) {
      if (value.length <= 4) {
        return '****';
      }
      return value.substring(0, 2) + '****' + value.substring(value.length - 2);
    },
    toggleSensitiveValue(row) {
      row.showValue = !row.showValue;
    },
    headerCellClassName() {
      return 'header-cell';
    }
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
  background-size: cover;
  background: linear-gradient(to bottom right, #dce8ff, #e4eeff, #e6cbfd) center;
  -webkit-background-size: cover;
  -o-background-size: cover;
  overflow: hidden;
}

.main-wrapper {
  // 顶部 63px 底部 35px
  height: calc(100vh - 63px - 35px);
  padding: 20px 22px 0;
  position: relative;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

.operation-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 0 16px 0;
}
.divider {
  height: 1px;
  background: #f3f1f1;
  margin-bottom: 20px;
}

.page-title {
  font-size: 24px;
  margin: 0;
}

.right-operations {
  display: flex;
  gap: 10px;
  margin-left: auto;
}

.search-input {
  width: 240px;
}

.btn-search {
  background: linear-gradient(135deg, #6b8cff, #a966ff);
  border: none;
  color: white;
}

.content-panel {
  display: flex;
  overflow: hidden;
  height: 100%;
  border-radius: 15px;
  background: transparent;
  border: 1px solid #fff;
}

.content-area {
  flex: 1;
  height: 100%;
  min-width: 600px;
  overflow: auto;
  background-color: white;
  display: flex;
  flex-direction: column;
}

.params-card {
  background: white;
  flex: 1;
  display: flex;
  flex-direction: column;
  border: none;
  box-shadow: none;
  overflow: hidden;

  ::v-deep .el-card__body {
    padding: 16px 22px;
    display: flex;
    flex-direction: column;
    flex: 1;
    overflow: hidden;
  }
}

.table_bottom {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 10px;
  // padding-bottom: 10px;
}

.ctrl_btn {
  display: flex;
}

.custom-pagination {
  display: flex;
  align-items: center;
  gap: 10px;

  .el-select {
    margin-right: 8px;
  }

  .pagination-btn:first-child,
  .pagination-btn:nth-child(2),
  .pagination-btn:nth-last-child(2),
  .pagination-btn:nth-child(3) {
    min-width: 60px;
    height: 32px;
    padding: 0 12px;
    border-radius: 4px;
    border: 1px solid #e4e7ed;
    background: #dee7ff;
    color: #606266;
    font-size: 14px;
    cursor: pointer;
    transition: all 0.3s ease;

    &:hover {
      background: #d7dce6;
    }

    &:disabled {
      opacity: 0.6;
      cursor: not-allowed;
    }
  }

  .pagination-btn:not(:first-child):not(:nth-child(3)):not(:nth-child(2)):not(:nth-last-child(2)) {
    min-width: 28px;
    height: 32px;
    padding: 0;
    border-radius: 4px;
    border: 1px solid transparent;
    background: transparent;
    color: #606266;
    font-size: 14px;
    cursor: pointer;
    transition: all 0.3s ease;

    &:hover {
      background: rgba(245, 247, 250, 0.3);
    }
  }

  .pagination-btn.active {
    background: #5f70f3 !important;
    color: #ffffff !important;
    border-color: #5f70f3 !important;

    &:hover {
      background: #6d7cf5 !important;
    }
  }

  .total-text {
    color: #909399;
    font-size: 14px;
    margin-left: 10px;
  }
}

:deep(.el-checkbox__inner) {
  background-color: #ffffff !important;
  border-color: #cccccc !important;
}

:deep(.el-checkbox__inner:hover) {
  border-color: #cccccc !important;
}

:deep(.el-checkbox__input.is-checked .el-checkbox__inner) {
  background-color: #5f70f3 !important;
  border-color: #5f70f3 !important;
}

@media (min-width: 1144px) {
  .table_bottom {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: 40px;
  }

  :deep(.transparent-table) {
    .el-table__body tr {
      td {
        padding-top: 16px;
        padding-bottom: 16px;
      }

      &+tr {
        margin-top: 10px;
      }
    }
  }
}

:deep(.el-table .el-button--text) {
  color: #7079aa;
}

:deep(.el-table .el-button--text:hover) {
  color: #5a64b5;
}

.el-button--success {
  background: #5bc98c;
  color: white;
}

:deep(.el-table .cell) {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.page-size-select {
  width: 100px;
  margin-right: 10px;

  :deep(.el-input__inner) {
    height: 32px;
    line-height: 32px;
    border-radius: 4px;
    border: 1px solid #e4e7ed;
    background: #dee7ff;
    color: #606266;
    font-size: 14px;
  }

  :deep(.el-input__suffix) {
    right: 6px;
    width: 15px;
    height: 20px;
    display: flex;
    justify-content: center;
    align-items: center;
    top: 6px;
    border-radius: 4px;
  }

  :deep(.el-input__suffix-inner) {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100%;
  }

  :deep(.el-icon-arrow-up:before) {
    content: "";
    display: inline-block;
    border-left: 6px solid transparent;
    border-right: 6px solid transparent;
    border-top: 9px solid #606266;
    position: relative;
    transform: rotate(0deg);
    transition: transform 0.3s;
  }
}

:deep(.el-table) {
  .el-table__body-wrapper {
    transition: height 0.3s ease;
  }
}

.el-table {
  // --table-max-height: calc(100vh - 40vh);
  max-height: var(--table-max-height);

  .el-table__body-wrapper {
    max-height: calc(var(--table-max-height) - 40px);
  }
}

:deep(.el-loading-mask) {
  background-color: rgba(255, 255, 255, 0.6) !important;
  backdrop-filter: blur(2px);
}

:deep(.el-loading-spinner .circular) {
  width: 28px;
  height: 28px;
}

:deep(.el-loading-spinner .path) {
  stroke: #6b8cff;
}

:deep(.el-loading-text) {
  color: #6b8cff !important;
  font-size: 14px;
  margin-top: 8px;
}
</style>
