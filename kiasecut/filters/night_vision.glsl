// @filter 夜視
// @category 風格
// @description 夜視鏡：放大亮度、整片變成綠色，帶雜訊，可以加上望遠鏡的圓框
// @param gain float 2.5 0.5 8 "增益"
// @param noise float 0.3 0 1 "雜訊"
// @param tint color #4dff6a "顏色"
// @param scope bool false "望遠鏡框"
vec4 effect(vec2 uv) {
    vec4 c = unpremultiply(src(uv));
    float l = dot(c.rgb, vec3(0.299, 0.587, 0.114)) * gain;
    l = l / (1.0 + l * 0.35);                               // bright parts roll off instead of clipping
    l += (rand(uv * resolution + float(frame) * 1.31) - 0.5) * noise * 0.4;
    float fine = smoothstep(1.5, 3.0, 4.0 / resolution.y / fwidth(uv.y));   // no moire when drawn small
    l *= 1.0 - 0.15 * fine * (0.5 + 0.5 * sin(uv.y * resolution.y * 1.5708));
    vec3 rgb = clamp(l, 0.0, 1.2) * tint.rgb;
    rgb = mix(rgb, vec3(1.0), max(l - 1.0, 0.0));
    vec2 d = (uv - 0.5) * vec2(resolution.x / resolution.y, 1.0);
    if (scope) {
        // two overlapping circles
        float r = min(length(d - vec2(0.27, 0.0)), length(d + vec2(0.27, 0.0)));
        rgb *= 1.0 - smoothstep(0.4, 0.43, r);
    } else {
        rgb *= 1.0 - 0.5 * smoothstep(0.3, 0.95, length(d));
    }
    return premultiply(vec4(clamp(rgb, 0.0, 1.0), c.a));
}
