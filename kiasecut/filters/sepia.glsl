// @filter 懷舊
// @category 色彩
// @description 泛黃的老照片色調
// @param amount float 1 0 1 "程度"
vec4 effect(vec2 uv) {
    vec4 c = unpremultiply(src(uv));
    vec3 s = vec3(dot(c.rgb, vec3(0.393, 0.769, 0.189)),
                  dot(c.rgb, vec3(0.349, 0.686, 0.168)),
                  dot(c.rgb, vec3(0.272, 0.534, 0.131)));
    return premultiply(vec4(clamp(mix(c.rgb, s, amount), 0.0, 1.0), c.a));
}
