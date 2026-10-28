// @filter 色相循環
// @category 動態
// @description 顏色隨時間繞著色環轉（彩虹變色）
// @param speed float 0.5 -10 10 "每秒幾圈"
// @param offset float 0 -180 180 "起始色相"
// @param saturation float 1 0 3 "飽和度"
// @param spread float 0 0 3 "畫面上的色差"

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
    // spread: the hue also changes across the picture, a rainbow sweeping over it
    float deg = offset + time * speed * 360.0 + (uv.x + uv.y) * spread * 180.0;
    vec3 rgb = hue_rotate(c.rgb, deg);
    float l = dot(rgb, vec3(0.299, 0.587, 0.114));
    rgb = mix(vec3(l), rgb, saturation);
    return premultiply(vec4(clamp(rgb, 0.0, 1.0), c.a));
}
