<template>
  <div class="welcome">
    <HeaderBar />
    <div class="main-wrapper">
      <div class="content-panel">
        <div class="content-area">
          <el-card class="params-card" shadow="never">
            <div class="operation-header">
              <h2 class="page-title">{{ $t('voiceClone.title') }}</h2>
              <div class="right-operations">
                <el-input :placeholder="$t('voiceClone.searchPlaceholder')" v-model="searchName" class="search-input"
                  @keyup.enter.native="handleSearch" clearable />
                <CustomButton type="confirm" icon="el-icon-search" @click="handleSearch">{{ $t('voiceClone.search') }}</CustomButton>
              </div>
            </div>
            <CustomTable
              ref="voiceCloneTable"
              :data="voiceCloneList"
              :columns="tableColumns"
              :loading="loading"
              :total="total"
              :current-page="currentPage"
              :page-size="pageSize"
              :page-size-options="pageSizeOptions"
              @size-change="handlePageSizeChange"
              @page-change="goToPage"
            >
              <template slot="name" slot-scope="scope">
                <el-input v-show="scope.row.isEdit" v-model="scope.row.name" size="mini" maxlength="64"
                  show-word-limit @blur="onNameBlur(scope.row)" @keyup.enter.native="onNameEnter(scope.row)"
                  ref="nameInput" />
                <span v-show="!scope.row.isEdit" class="name-view">
                  <i class="el-icon-edit" @click="handleEditName(scope.row)" style="cursor: pointer;"></i>
                  <span @click="handleEditName(scope.row)">
                    {{ scope.row.name || '-' }}
                  </span>
                </span>
              </template>
              <template slot="trainStatus" slot-scope="scope">
                <div class="status-button" :class="getStatusButtonClass(scope.row)">
                  <span>{{ getTrainStatusText(scope.row) }}</span>
                </div>
              </template>
              <template slot="Details" slot-scope="scope">
                <el-tooltip :content="getTooltipContent(scope.row)" placement="top">
                  <el-button size="mini" type="text" icon="el-icon-info"
                    @click="handleViewDetails(scope.row)">
                  </el-button>
                </el-tooltip>
              </template>
              <template slot="action" slot-scope="scope">
                <el-button v-if="scope.row.hasVoice" size="mini" type="text"
                  @click="handlePlay(scope.row)">
                  {{ playingRowId === scope.row.id ? $t('voiceClone.stop') : $t('voiceClone.play') }}
                </el-button>
                <el-button size="mini" type="text" @click="handleUpload(scope.row)">
                  {{ $t('voiceClone.upload') }}
                </el-button>
                <el-button v-if="scope.row.hasVoice" size="mini" type="text"
                  @click="handleClone(scope.row)" :loading="scope.row._cloning">
                  {{ $t('voiceClone.clone') }}
                </el-button>
              </template>
              <!-- 占位作用保持分页在右边展示 -->
              <template slot="footer-btns">
                <div></div>
              </template>
            </CustomTable>
          </el-card>
        </div>
      </div>
    </div>

    <el-footer>
      <version-footer />
    </el-footer>

    <VoiceCloneDialog :visible.sync="cloneDialogVisible" :voiceCloneData="currentVoiceClone"
      @success="handleCloneSuccess" />
  </div>
</template>

<script>
import Api from "@/apis/api";
import HeaderBar from "@/components/HeaderBar.vue";
import VersionFooter from "@/components/VersionFooter.vue";
import VoiceCloneDialog from "@/components/VoiceCloneDialog.vue";
import CustomButton from "@/components/CustomButton.vue";
import CustomTable from "@/components/CustomTable.vue";
import { formatDate } from "@/utils/format";

export default {
  components: { HeaderBar, VersionFooter, VoiceCloneDialog, CustomButton, CustomTable },
  data() {
    return {
      searchName: "",
      loading: false,
      voiceCloneList: [],
      currentPage: 1,
      pageSize: 10,
      pageSizeOptions: [10, 20, 50, 100],
      total: 0,
      cloneDialogVisible: false,
      currentVoiceClone: {},
      voiceCloneForm: {
        modelId: "",
        voiceIds: [],
        userId: null
      },
      currentAudio: null,
      playingRowId: null,
      tableColumns: []
    };
  },
  created() {
    this.initTableColumns();
    this.fetchVoiceCloneList();
  },
  methods: {
    initTableColumns() {
      this.tableColumns = [
        { prop: 'voiceId', label: this.$t('voiceClone.voiceId'), align: 'center' },
        { prop: 'name', label: this.$t('voiceClone.name'), align: 'center' },
        { prop: 'languages', label: this.$t('voiceClone.languages'), align: 'center' },
        { prop: 'trainStatus', label: this.$t('voiceClone.trainStatus'), align: 'center' },
        { prop: 'Details', label: this.$t('voiceClone.Details'), align: 'center', width: 120 },
        { prop: 'action', label: this.$t('voiceClone.action'), align: 'center', width: 230 }
      ];
    },
    getTooltipContent(row) {
      if (!row.hasVoice) {
        return '待上传';
      }
      switch (row.trainStatus) {
        case 0:
          return '待复刻';
        case 2:
          return '训练成功';
        case 3:
          if (row.trainError) {
            return `训练失败：${row.trainError}`;
          }
          return '训练失败';
        default:
          return '';
      }
    },
    handleViewDetails(row) {
      console.log('查看详情:', row);
    },
    handlePageSizeChange(val) {
      this.pageSize = val;
      this.currentPage = 1;
      this.fetchVoiceCloneList();
    },
    goToPage(page) {
      if (page !== this.currentPage) {
        this.currentPage = page;
        this.fetchVoiceCloneList();
      }
    },
    fetchVoiceCloneList() {
      this.loading = true;
      const params = {
        page: this.currentPage,
        limit: this.pageSize,
        name: this.searchName || "",
        orderField: "create_date",
        order: "desc"
      };
      Api.voiceClone.getVoiceCloneList(params, (res) => {
        this.loading = false;
        res = res.data;
        if (res.code === 0) {
          this.voiceCloneList = res.data.list;
          this.total = res.data.total || 0;
        } else {
          this.voiceCloneList = [];
          this.total = 0;
          this.$message.error({
            message: res?.data?.msg || this.$t('voiceClone.deleteFailed'),
            showClose: true
          });
        }
      });
    },
    handleSearch() {
      this.currentPage = 1;
      this.fetchVoiceCloneList();
    },
    formatDate,
    getTrainStatusText(row) {
      if (!row.hasVoice) {
        return this.$t('voiceClone.waitingUpload');
      }
      switch (row.trainStatus) {
        case 0:
          return this.$t('voiceClone.waitingTraining');
        case 2:
          return this.$t('voiceClone.trainSuccess');
        case 3:
          return this.$t('voiceClone.trainFailed');
        default:
          return '';
      }
    },
    getStatusButtonClass(row) {
      if (!row.hasVoice || row.trainStatus === 0) {
        return 'status-waiting';
      } else if (row.trainStatus === 2) {
        return 'status-success';
      } else if (row.trainStatus === 3) {
        return 'status-failed';
      }
      return '';
    },
    handleClone(row) {
      if (row._cloning) {
        return;
      }
      this.$set(row, '_cloning', true);
      const params = { cloneId: row.id };
      try {
        Api.voiceClone.cloneAudio(params, (res) => {
          try {
            res = res.data;
            if (res.code === 0) {
              this.$message.success(this.$t('message.success'));
              this.fetchVoiceCloneList();
            } else {
              this.$message.error(res.msg || this.$t('message.error'));
              this.fetchVoiceCloneList();
            }
          } catch (error) {
            console.error('处理响应时出错:', error);
            this.$message.error('处理响应时出错');
            this.fetchVoiceCloneList();
          } finally {
            this.$set(row, '_cloning', false);
          }
        }, (error) => {
          console.error('API调用失败:', error);
          this.$message.error('克隆失败，请将鼠标悬停在错误提示上，查看错误详情');
          this.fetchVoiceCloneList();
          this.$set(row, '_cloning', false);
        });
      } catch (error) {
        console.error('调用API时出错:', error);
        this.$message.error('调用API时出错');
        this.fetchVoiceCloneList();
        this.$set(row, '_cloning', false);
      }
    },
    handleCloneSuccess() {
      this.fetchVoiceCloneList();
    },
    handleEditName(row) {
      this.$set(row, 'isEdit', true);
      this.$nextTick(() => {
        const input = this.$refs.nameInput;
        if (input) {
          if (Array.isArray(input)) {
            const idx = this.voiceCloneList.indexOf(row);
            if (input[idx]) {
              input[idx].focus();
            }
          } else {
            input.focus();
          }
        }
      });
    },
    submitName(row) {
      if (row._submitting) {
        return;
      }
      row._submitting = true;
      const params = { id: row.id, name: row.name };
      Api.voiceClone.updateName(params, (res) => {
        res = res.data;
        if (res.code === 0) {
          this.$message.success(this.$t('voiceClone.updateNameSuccess') || '名称更新成功');
        } else {
          this.$message.error(res.msg || this.$t('voiceClone.updateNameFailed') || '名称更新失败');
          this.fetchVoiceCloneList();
        }
        row._submitting = false;
      });
    },
    onNameBlur(row) {
      row.isEdit = false;
      setTimeout(() => {
        this.submitName(row);
      }, 100);
    },
    onNameEnter(row) {
      row.isEdit = false;
      this.submitName(row);
    },
    handlePlay(row) {
      if (this.playingRowId === row.id && this.currentAudio) {
        this.stopCurrentAudio();
        return;
      }
      this.stopCurrentAudio();
      Api.voiceClone.getAudioId(row.id, (res) => {
        res = res.data;
        if (res.code === 0) {
          const uuid = res.data;
          const audioUrl = Api.voiceClone.getPlayVoiceUrl(uuid);
          const audio = new Audio(audioUrl);
          this.currentAudio = audio;
          this.playingRowId = row.id;
          audio.addEventListener('ended', () => {
            this.playingRowId = null;
            this.currentAudio = null;
          });
          audio.addEventListener('error', () => {
            this.playingRowId = null;
            this.currentAudio = null;
          });
          audio.play().catch(err => {
            console.error('播放失败:', err);
            this.$message.error(this.$t('voiceClone.playFailed') || '播放失败');
            this.playingRowId = null;
            this.currentAudio = null;
          });
        } else {
          this.$message.error(res.msg || this.$t('voiceClone.audioNotExist') || '音频不存在');
        }
      });
    },
    stopCurrentAudio() {
      if (this.currentAudio) {
        this.currentAudio.pause();
        this.currentAudio.currentTime = 0;
        this.currentAudio = null;
      }
      this.playingRowId = null;
    },
    handleUpload(row) {
      this.currentVoiceClone = row;
      this.cloneDialogVisible = true;
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

.page-title {
  font-weight: 500;
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
    padding: 14px 20px;
    display: flex;
    flex-direction: column;
    flex: 1;
    overflow: hidden;
  }
}

.name-view {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;

  i {
    color: #909399;
    font-size: 14px;

    &:hover {
      color: #5a64b5;
    }
  }

  span {
    &:hover {
      color: #5a64b5;
    }
  }
}

.status-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 4px 10px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
}

.status-waiting {
  background-color: #f5f7fa;
  color: #909399;
  border: 1px solid #e4e7ed;
}

.status-success {
  background-color: #f6ffed;
  color: #52c41a;
  border: 1px solid #b7eb8f;
}

.status-failed {
  background-color: #fff2f0;
  color: #ff4d4f;
  border: 1px solid #ffccc7;
}

:deep(.el-table .el-button--text) {
  color: #7079aa;
}

:deep(.el-table .el-button--text:hover) {
  color: #5a64b5;
}
</style>