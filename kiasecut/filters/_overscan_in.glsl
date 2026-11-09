// @filter 延伸範圍：放進
// @description 內部用：節點效果有「延伸範圍」時，把片段的畫面放進比畫面大的工作區中央，四周是透明
// @source 圖像

vec4 effect(vec2 uv) {
    if (any(lessThan(uv, vec2(0.0))) || any(greaterThan(uv, vec2(1.0)))) return vec4(0.0);
    return src(uv);
}
