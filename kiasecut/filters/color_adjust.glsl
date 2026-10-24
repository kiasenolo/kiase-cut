// @filter 調色
// @category 色彩
// @description 亮度、對比、飽和度、色相
// @param brightness float 0 -1 1 "亮度"
// @param contrast float 1 0 3 "對比"
// @param saturation float 1 0 3 "飽和度"
// @param hue float 0 -180 180 "色相"
vec3 hue_rotate(vec3 c, float deg) {
    float a = radians(deg);
    float cs = cos(a), sn = sin(a);
    mat3 m = mat3(
        0.299 + 0.701 * cs + 0.168 * sn, 0.299 - 0.299 * cs - 0.328 * sn, 0.299 - 0.300 * cs + 1.250 * sn,
        0.587 - 0.587 * cs + 0.330 * sn, 0.587 + 0.413 * cs + 0.035 * sn, 0.587 - 0.588 * cs - 1.050 * sn,
        0.114 - 0.114 * cs - 0.497 * sn, 0.114 - 0.114 * cs + 0.292 * sn, 0.114 + 0.886 * cs - 0.203 * sn);
    return m * c;
}
vec4 effect(vec2 uv) {
    vec4 c = unpremultiply(src(uv));
    vec3 rgb = hue_rotate(c.rgb, hue);
    float l = dot(rgb, vec3(0.299, 0.587, 0.114));
    rgb = mix(vec3(l), rgb, saturation);
    rgb = (rgb - 0.5) * contrast + 0.5 + brightness;
    return premultiply(vec4(clamp(rgb, 0.0, 1.0), c.a));
}
