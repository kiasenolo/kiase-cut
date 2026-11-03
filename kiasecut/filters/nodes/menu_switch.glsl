// @filter 選單切換
// @category 轉換器
// @description 節點用：照 Blender 的「選單切換」節點（Menu Switch）：從好幾張圖裡用選單選一張輸出，沒被選到的圖不會被運算。選項數量可以選 2 到 8 張；選單可以在效果面板做成參數（像 Blender 的選單輸入），用來一次切換整個效果
// @source "選項 1"
// @input i2 "選項 2"
// @input i3 "選項 3"
// @input i4 "選項 4"
// @input i5 "選項 5"
// @input i6 "選項 6"
// @input i7 "選項 7"
// @input i8 "選項 8"
// @param count menu 3 "2|3|4|5|6|7|8" "選項數量"
// @param choice menu "選項 1" "選項 1|選項 2|選項 3|選項 4|選項 5|選項 6|選項 7|選項 8" "選單"
// @show i3 count == 3|4|5|6|7|8
// @show i4 count == 4|5|6|7|8
// @show i5 count == 5|6|7|8
// @show i6 count == 6|7|8
// @show i7 count == 7|8
// @show i8 count == 8
// @use src choice == 選項 1
// @use i2 choice == 選項 2
// @use i3 choice == 選項 3
// @use i4 choice == 選項 4
// @use i5 choice == 選項 5
// @use i6 choice == 選項 6
// @use i7 choice == 選項 7
// @use i8 choice == 選項 8

vec4 effect(vec2 uv) {
    // (a choice past the number of options gives nothing, as Blender's menu with no item chosen)
    if (choice >= count + 2) return vec4(0.0);
    if (choice == 0) return src(uv);
    if (choice == 1) return input_i2(uv);
    if (choice == 2) return input_i3(uv);
    if (choice == 3) return input_i4(uv);
    if (choice == 4) return input_i5(uv);
    if (choice == 5) return input_i6(uv);
    if (choice == 6) return input_i7(uv);
    if (choice == 7) return input_i8(uv);
    return vec4(0.0);
}
