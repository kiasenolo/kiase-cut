// @filter VHS 錄影帶
// @category 風格
// @description 老錄影帶：顏色往旁邊暈開、每一行輕微抖動、偶爾一條干擾帶捲過，底部有磁頭切換的雜訊
// @param amount float 0.7 0 1 "強度"
// @param bleed float 8 0 30 "色彩暈開"
// @param tracking float 0.5 0 1 "訊號干擾"
// @param noise float 0.3 0 1 "雜訊"

vec3 to_yiq(vec3 c) {
    return mat3(0.299, 0.596, 0.211, 0.587, -0.274, -0.523, 0.114, -0.322, 0.312) * c;
}
vec3 from_yiq(vec3 c) {
    return mat3(1.0, 1.0, 1.0, 0.956, -0.272, -1.106, 0.621, -0.647, 1.703) * c;
}

vec4 effect(vec2 uv) {
    float f = float(frame);
    float row = floor(uv.y * resolution.y / 2.0);        // the tape's lines, 2 canvas px each
    // every line slightly sideways; more in the band rolling down the picture and at the bottom
    float shift = (rand(vec2(row, f)) - 0.5) * 2.0 * amount;
    float band = fract(time * 0.13 + 0.3);
    float in_band = exp(-pow((uv.y - band) / 0.03, 2.0)) * tracking;
    shift += (rand(vec2(row * 0.37, f + 1.0)) - 0.3) * 40.0 * in_band;
    float bottom = smoothstep(0.96, 1.0, uv.y) * amount;
    shift += bottom * (10.0 + 20.0 * rand(vec2(row, f + 2.0)));
    vec2 at = uv + vec2(shift / resolution.x, 0.0);

    // brightness a little soft, colour smeared to the right
    vec4 a = src(at);
    vec3 y3 = (src(at - vec2(1.0 / resolution.x, 0.0)).rgb + a.rgb * 2.0 + src(at + vec2(1.0 / resolution.x, 0.0)).rgb) / 4.0;
    float luma = to_yiq(y3).x;
    vec2 iq = vec2(0.0);
    for (int i = 0; i < 8; i++) {
        float o = -bleed * float(i) / 7.0 - bleed * 0.3;
        iq += to_yiq(src(at + vec2(o / resolution.x, 0.0)).rgb).yz;
    }
    iq /= 8.0;
    vec3 tape = from_yiq(vec3(luma, iq * 0.85));
    tape = mix(tape, vec3(0.06, 0.04, 0.08) + tape * 0.9, 0.5);   // lifted, slightly purple blacks

    float n = rand(vec2(floor(uv.x * resolution.x / 2.0), row + f * 17.0));
    tape += (n - 0.5) * noise * 0.25;
    tape += step(0.6, n) * in_band * 0.6;                           // white specks in the band
    tape = mix(tape, vec3(n), bottom * 0.5);
    vec3 rgb = mix(a.rgb, clamp(tape, 0.0, 1.0) * a.a, amount);
    return vec4(rgb, a.a);
}
