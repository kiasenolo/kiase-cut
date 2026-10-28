// @filter 分離色調
// @category 色彩
// @description 暗部和亮部各自染上一個顏色，明暗不變（預設是電影感的青橙色調）
// @param shadows color #0f7f8f "暗部顏色"
// @param highlights color #ff8a3d "亮部顏色"
// @param amount float 0.5 0 1 "強度"
// @param balance float 0 -1 1 "平衡"
vec4 effect(vec2 uv) {
    vec4 c = unpremultiply(src(uv));
    vec3 w = vec3(0.299, 0.587, 0.114);
    float l = dot(c.rgb, w);
    float k = smoothstep(0.0, 1.0, clamp(l + balance * 0.5, 0.0, 1.0));
    vec3 tone = mix(shadows.rgb, highlights.rgb, k);
    vec3 rgb = mix(c.rgb, c.rgb * tone * 2.0, amount * 0.6);
    rgb += l - dot(rgb, w);                                // as bright as before
    return premultiply(vec4(clamp(rgb, 0.0, 1.0), c.a));
}
