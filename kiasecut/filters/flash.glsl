// @filter 閃光
// @category 動態
// @description 一閃一閃再淡掉；頻率 0：只在開頭閃一次，淡到片段結束
// @param flash color #ffffff "顏色"
// @param intensity float 0.8 0 1 "強度"
// @param frequency float 2 0 30 "每秒次數"
// @param sharpness float 3 0.5 10 "消退速度"
vec4 effect(vec2 uv) {
    vec4 c = src(uv);
    float ph = frequency > 0.0 ? fract(time * frequency) : progress;
    float v = pow(1.0 - ph, sharpness) * intensity * flash.a;
    return vec4(mix(c.rgb, flash.rgb * c.a, v), c.a);
}
