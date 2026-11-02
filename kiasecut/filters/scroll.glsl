// @filter 滾動
// @category 動態
// @description 讓畫面持續往一個方向捲動（像 OBS 的 Scroll），可以循環
// @param speed_x float 0 -5000 5000 "水平速度 px/秒"
// @param speed_y float 0 -5000 5000 "垂直速度 px/秒"
// @param loop bool true "循環"
vec4 effect(vec2 uv) {
    vec2 p = uv - vec2(speed_x, speed_y) * time / resolution;
    if (loop) return src(fract(p));
    if (p.x < 0.0 || p.x > 1.0 || p.y < 0.0 || p.y > 1.0) return vec4(0.0);
    return src(p);
}
