// @filter 呼吸縮放
// @category 動態
// @description 畫面規律地放大再縮回
// @param amount float 0.08 0 0.5 "放大幅度"
// @param frequency float 1 0 10 "每秒次數"
// @param center vec2 0.5,0.5 0 1 "中心"
vec4 effect(vec2 uv) {
    float s = 1.0 + amount * (0.5 - 0.5 * cos(6.2831853 * time * frequency));
    return src(center + (uv - center) / s);
}
