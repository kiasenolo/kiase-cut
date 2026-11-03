// @filter 數值
// @category 輸入
// @description 節點用：照 Blender 的「數值」節點：一個常數，整張圖都是這個數字（黑白的圖）。接到別的節點的數字輸入或參數；數字在節點上直接輸入或拖曳
// @param value float 0.5 -1000000 1000000 "數值"

vec4 effect(vec2 uv) {
    return vec4(vec3(value), 1.0);
}
