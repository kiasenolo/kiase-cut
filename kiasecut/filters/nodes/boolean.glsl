// @filter 布林
// @category 輸入
// @description 節點用：照 Blender 的「布林」節點（Boolean）：一個開關，打開是 1（整張圖白），關掉是 0（黑）。接到別的節點的數字輸入或參數（例如切換）
// @param value bool false "布林"

vec4 effect(vec2 uv) {
    return vec4(vec3(value ? 1.0 : 0.0), 1.0);
}
