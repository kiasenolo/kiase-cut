// @filter 銳利化
// @category 模糊
// @description 加強邊緣
// @param amount float 1 0 5 "強度"
// @param radius float 1 0.5 8 "半徑"
vec4 effect(vec2 uv) {
    vec2 px = vec2(radius * scale) / resolution;
    vec4 c = src(uv);
    vec4 blur = (src(uv + vec2(px.x, 0.0)) + src(uv - vec2(px.x, 0.0)) +
                 src(uv + vec2(0.0, px.y)) + src(uv - vec2(0.0, px.y))) * 0.25;
    return vec4(clamp(c.rgb + (c.rgb - blur.rgb) * amount, 0.0, c.a), c.a);
}
