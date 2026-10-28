// @filter 鏡頭光斑
// @category 光效
// @description 強光照進鏡頭：光源的亮點、橫向光條、光環，和沿著畫面中心排開的鬼影
// @param position vec2 0.25,0.3 0 1 "光源位置"
// @param intensity float 1 0 3 "強度"
// @param size float 1 0.2 3 "大小"
// @param tint color #ffd9a8 "顏色"
// @param streak float 0.6 0 1 "橫向光條"
// @param ghosts float 0.5 0 1 "鬼影"
// @param halo float 0.3 0 1 "光環"

// a soft disc of radius r with a brighter rim
float ghost(vec2 p, vec2 at, float r) {
    float d = length(p - at) / r;
    return (1.0 - smoothstep(0.85, 1.0, d)) * (0.4 + 0.6 * d * d);
}

vec4 effect(vec2 uv) {
    vec4 c = src(uv);
    vec2 asp = vec2(resolution.x / resolution.y, 1.0);
    vec2 p = (uv - 0.5) * asp;
    vec2 s = (position - 0.5) * asp;
    vec2 d = p - s;
    float r = length(d);
    vec3 col = tint.rgb;

    vec3 light = col * (exp(-r * r / (0.0012 * size * size)) * 1.5           // the hot centre
                        + pow(max(0.0, 1.0 - r / (0.7 * size)), 3.0) * 0.45);   // and its wide glow
    float st = exp(-abs(d.y) / (0.0035 * size)) * exp(-abs(d.x) / (0.45 * size));
    light += mix(col, vec3(0.55, 0.75, 1.0), 0.5) * st * streak * 1.2;
    float ring = exp(-pow((r - 0.28 * size) / (0.012 * size), 2.0));
    float hue = atan(d.y, d.x) * 2.0;
    light += (0.6 + 0.4 * cos(vec3(0.0, 2.1, 4.2) + hue)) * col * ring * halo * 0.5;

    // ghosts: copies of the light's aperture along the line from the light through the centre
    vec3 g = vec3(0.0);
    g += vec3(0.4, 0.8, 1.0) * ghost(p, s * -0.35, 0.05 * size);
    g += vec3(1.0, 0.6, 0.3) * ghost(p, s * -0.7, 0.09 * size);
    g += vec3(0.5, 1.0, 0.6) * ghost(p, s * 0.45, 0.035 * size);
    g += vec3(0.8, 0.5, 1.0) * ghost(p, s * -1.1, 0.14 * size) * 0.6;
    g += vec3(1.0, 0.9, 0.6) * ghost(p, s * -1.5, 0.06 * size);
    light += g * col * ghosts * 0.6;

    light = clamp(light * intensity * tint.a, 0.0, 1.0) * c.a;
    return vec4(c.rgb + light - c.rgb * light, c.a);     // screen
}
