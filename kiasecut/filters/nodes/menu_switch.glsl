// @filter 選單切換
// @category 轉換器
// @description 節點用：照 Blender 的「選單切換」節點（Menu Switch）：用選單選一張圖輸出，沒被選到的圖不會被運算。選項自己加（把線拉到最下面的空插槽）、改名（在選項上按右鍵）、刪除；選單可以在效果面板做成參數，一次切換整個效果
// @dynamic menu_switch
// @source "選項 1"
// @input i2 "選項 2"
// @input i3 "選項 3"
// @param choice menu "選項 1" "選項 1|選項 2|選項 3" "選單"
// @use src choice == 選項 1
// @use i2 choice == 選項 2
// @use i3 choice == 選項 3

vec4 effect(vec2 uv) {
    switch (choice) {
    case 0: return src(uv);
    case 1: return input_i2(uv);
    case 2: return input_i3(uv);
    }
    return vec4(0.0);
}
