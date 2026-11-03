// @filter 索引切換
// @category 轉換器
// @description 節點用：照 Blender 的「索引切換」節點（Index Switch）：用索引（整數）選第幾張圖輸出，從 0 開始；索引超出範圍就什麼都不輸出。沒被選到的圖不會被運算。輸入自己加（把線拉到最下面的空插槽）、刪除（在輸入上按右鍵）。索引可以接一個數字，也可以在效果面板做成參數
// @dynamic index_switch
// @source "0"
// @input i2 "1"
// @param index int 0 0 1000 "索引"
// @use src index == 0
// @use i2 index == 1

vec4 effect(vec2 uv) {
    switch (index) {
    case 0: return src(uv);
    case 1: return input_i2(uv);
    }
    return vec4(0.0);
}
