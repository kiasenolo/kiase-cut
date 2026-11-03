// @filter 色相／飽和度／明度
// @category 色彩
// @description 節點用：照 Blender 的「色相／飽和度／明度」節點：色相 0.5 是不變，其他三項 1 是不變；係數是和原圖的混合
// @source 顏色
// @param hue float 0.5 0 1 "色相"
// @param sat float 1 0 2 "飽和度"
// @param val float 1 0 2 "明度"
// @param fac float 1 0 1 "係數"

vec3 rgb_to_hsv(vec3 c) {
    float mx = max(c.r, max(c.g, c.b)), mn = min(c.r, min(c.g, c.b)), d = mx - mn;
    float h = 0.0;
    if (d > 1e-6) {
        if (mx == c.r) h = mod((c.g - c.b) / d, 6.0);
        else if (mx == c.g) h = (c.b - c.r) / d + 2.0;
        else h = (c.r - c.g) / d + 4.0;
        h /= 6.0;
    }
    return vec3(h, mx > 1e-6 ? d / mx : 0.0, mx);
}

vec3 hsv_to_rgb(vec3 c) {
    vec3 k = clamp(abs(mod(c.x * 6.0 + vec3(0.0, 4.0, 2.0), 6.0) - 3.0) - 1.0, 0.0, 1.0);
    return c.z * mix(vec3(1.0), k, c.y);
}

vec4 effect(vec2 uv) {
    vec4 a = unpremultiply(src(uv));
    vec3 h = rgb_to_hsv(a.rgb);
    h.x = fract(h.x + hue - 0.5 + 1.0);
    h.y = clamp(h.y * sat, 0.0, 1.0);
    h.z = h.z * val;
    return premultiply(vec4(mix(a.rgb, hsv_to_rgb(h), clamp(fac, 0.0, 1.0)), a.a));
}
