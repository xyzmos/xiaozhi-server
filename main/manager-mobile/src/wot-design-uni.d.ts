import type { Component } from 'vue'

// wot-design-uni 1.9.1 exposes raw Vue source through its global declarations.
// Keep the components used by this app recognizable without pulling that source into vue-tsc.
declare module 'vue' {
  export interface GlobalComponents {
    WdActionSheet: Component
    WdButton: Component
    WdCheckbox: Component
    WdConfigProvider: Component
    WdFab: Component
    WdIcon: Component
    WdImg: Component
    WdInput: Component
    WdLoading: Component
    WdMessageBox: Component
    WdNavbar: Component
    WdPicker: Component
    WdPopup: Component
    WdSegmented: Component
    WdSlider: Component
    WdStatusTip: Component
    WdSwipeAction: Component
    WdSwitch: Component
    WdTabbar: Component
    WdTabbarItem: Component
    WdTag: Component
    WdToast: Component
  }
}
