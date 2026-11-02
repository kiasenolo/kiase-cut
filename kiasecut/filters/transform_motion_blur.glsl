// @filter 動態模糊
// @category 模糊
// @description 片段的位置、縮放、旋轉有動畫時，沿著它移動的方向模糊（像 After Effects 的動態模糊）；片段沒在動的時候不模糊
// @param shutter float 180 0 720 "快門角度"
// @param samples int 8 2 64 "取樣"
// 動態效果：畫面本身不變，程式把片段在快門打開的這段時間裡畫幾次再平均；片段的其他效果套在模糊後的畫面上
vec4 effect(vec2 uv) {
    return src(uv);
}
