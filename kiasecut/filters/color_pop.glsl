// @filter 色彩聚焦
// @category 色彩
// @description 只留下一種顏色，其他都變成黑白
// @param keep color #e02020 "保留的顏色"
// @param range float 25 0 180 "色相範圍"
// @param softness float 15 0 90 "柔和度"
// @param amount float 1 0 1 "其他變灰"

float hue_of(vec3 c) {
    float mx = max(c.r, max(c.g, c.b)), mn = min(c.r, min(c.g, c.b));
    float d = mx - mn;
    if (d < 1e-5) return 0.0;
    float h = mx == c.r ? mod((c.g - c.b) / d, 6.0) : mx == c.g ? (c.b - c.r) / d + 2.0 : (c.r - c.g) / d + 4.0;
    return h * 60.0;
}
float sat_of(vec3 c) {
    float mx = max(c.r, max(c.g, c.b));
    return mx > 0.0 ? (mx - min(c.r, min(c.g, c.b))) / mx : 0.0;
}

vec4 effect(vec2 uv) {
    vec4 c = unpremultiply(src(uv));
    float dh = abs(hue_of(c.rgb) - hue_of(keep.rgb));
    dh = min(dh, 360.0 - dh);
    float kept = (1.0 - smoothstep(range, range + softness + 0.01, dh)) * smoothstep(0.08, 0.25, sat_of(c.rgb));
    float l = dot(c.rgb, vec3(0.299, 0.587, 0.114));
    vec3 rgb = mix(c.rgb, vec3(l), amount * (1.0 - kept));
    return premultiply(vec4(rgb, c.a));
}
