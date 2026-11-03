// @filter 圖片來源
// @category 節點
// @description 節點用：把來源（圖片、影片、複合片段、軌道）擺在片段上它的位置，其他地方透明
// @param color color #00000000 "底色"

vec4 effect(vec2 uv) {
    return premultiply(color);
}
