// @filter 故障
// @category 風格
// @description 橫向切片錯位加色差，隨時間跳動
// @param intensity float 0.5 0 1 "強度"
// @param blocks float 24 2 200 "切片數"
// @param speed float 12 0 60 "跳動速度"
vec4 effect(vec2 uv) {
    float t = floor(time * speed);
    float row = floor(uv.y * blocks);
    float on = step(1.0 - 0.6 * intensity, rand(vec2(row, t)));
    float off = (rand(vec2(row + 7.0, t)) - 0.5) * 0.25 * intensity * on;
    float split = on * intensity * 6.0 / resolution.x;
    vec2 p = vec2(uv.x + off, uv.y);
    vec4 r = src(p + vec2(split, 0.0));
    vec4 g = src(p);
    vec4 b = src(p - vec2(split, 0.0));
    return vec4(r.r, g.g, b.b, max(g.a, max(r.a, b.a)));
}
