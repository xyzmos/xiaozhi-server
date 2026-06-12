<template>
  <el-button
    :class="['custom-button', `custom-button--${type}`]"
    v-bind="$attrs"
    @click="$emit('click', $event)"
  >
    <slot />
  </el-button>
</template>

<script>
export default {
  name: 'CustomButton',
  props: {
    type: {
      type: String,
      default: 'default',
      validator: (val) => ['default', 'confirm'].includes(val)
    }
  }
};
</script>

<style lang="scss" scoped>
.custom-button--default {
  background: transparent;
  color: #8099fc;
  border: 1px solid #adbdff;
  border-radius: 6px;
  transition: all 0.3s ease;

  &.el-button--small {
    font-size: 14px;
  }

  &:hover {
    background: #f1f2ff;
    color: #8099fc;
    border-color: #adbdff;
    box-shadow: 0 2px 8px rgba(128, 153, 252, 0.3);
    transform: translateY(-2px);
  }

  &.is-disabled,
  &.is-disabled:hover {
    background: transparent;
    color: #c0c4cc;
    border-color: #e4e7ed;
    box-shadow: none;
    transform: none;
    cursor: not-allowed;
  }
}

.custom-button--confirm {
  width: fit-content;
  background: linear-gradient(to right, #4a7cfd, #8154fc);
  color: white;
  border: none;
  border-radius: 6px;
  transition: all 0.3s ease;

  &.el-button--small {
    font-size: 14px;
  }

  &:hover {
    background: linear-gradient(to right, #6b8cff, #9a7cff);
    color: white;
    border-color: transparent;
    box-shadow: 0 2px 8px rgba(74, 124, 253, 0.3);
    transform: translateY(-2px);
  }

  &.is-disabled,
  &.is-disabled:hover {
    background: linear-gradient(to right, #a0b4fd, #b8a4fd);
    color: rgba(255, 255, 255, 0.6);
    border-color: transparent;
    box-shadow: none;
    transform: none;
    cursor: not-allowed;
  }
}
</style>
