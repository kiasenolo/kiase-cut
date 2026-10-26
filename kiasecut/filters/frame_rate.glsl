// @filter 降低幀數
// @category 時間
// @description 讓片段像低幀率一樣一格一格地跳（停格動畫感）：影片、複合片段和關鍵幀動畫都只在這個幀率更新
// @param fps float 12 1 60 "每秒幾格"
// 時間效果：畫面本身不變，程式在畫這個片段之前把它的時間對齊到每 1/fps 秒一格
vec4 effect(vec2 uv) {
    return src(uv);
}
