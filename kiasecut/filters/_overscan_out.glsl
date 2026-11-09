// @filter 延伸範圍：取回
// @description 內部用：節點效果有「延伸範圍」時，把比畫面大的工作區裡畫面的部分取回來
// @source 圖像

vec4 effect(vec2 uv) {
    return src(uv);
}
