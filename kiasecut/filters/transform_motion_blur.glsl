// @filter 動態模糊
// @category 模糊
// @description 片段畫面裡任何在動的東西都沿著移動的方向模糊（像 After Effects 的 CC Force Motion Blur）：關鍵幀、表達式、文字和形狀的動畫、複合片段裡的片段、影片的畫面；沒在動的時候不模糊
// @param shutter float 180 0 720 "快門角度"
// @param samples int 16 2 64 "取樣"
// 動態效果：畫面本身不變，程式把整個片段（連同它的其他效果）在快門打開的這段時間裡畫「取樣」次再平均
vec4 effect(vec2 uv) {
    return src(uv);
}
