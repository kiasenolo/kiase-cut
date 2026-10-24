// @filter 魚眼
// @category 扭曲
// @description 正值：中間鼓起來放大；負值：往中間縮
// @param strength float 0.5 -1 1 "強度"
// @param radius float 0.6 0.05 2 "範圍"
// @param center vec2 0.5,0.5 0 1 "中心"
vec4 effect(vec2 uv) {
    vec2 asp = vec2(resolution.x / resolution.y, 1.0);
    vec2 d = (uv - center) * asp;
    float f = length(d) / radius;
    if (f >= 1.0) return src(uv);
    float k = 1.0 - min(strength, 0.95) * (1.0 - f) * (1.0 - f);
    return src(center + d * k / asp);
}
