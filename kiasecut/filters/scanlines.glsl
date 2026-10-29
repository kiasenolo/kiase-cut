// @filter 掃描線
// @category 風格
// @description 老電視的橫向掃描線，可以讓它捲動、閃爍
// @param strength float 0.4 0 1 "強度"
// @param spacing float 4 1 40 "間距"
// @param speed float 0 -20 20 "捲動速度"
// @param flicker float 0.2 0 1 "閃爍"
vec4 effect(vec2 uv) {
    vec4 c = src(uv);
    float y = uv.y * resolution.y / spacing - time * speed;
    float line = 0.5 + 0.5 * sin(y * 6.2831853);
    float f = 1.0 - flicker * 0.25 * rand(vec2(frame_phase().x, 3.7 + frame_phase().y * 0.37));
    return vec4(c.rgb * (1.0 - strength * line) * f, c.a);
}
