// @filter VHS 錄影帶
// @category 風格
// @description 老錄影帶：顏色往旁邊暈開、每一行輕微抖動、偶爾一條干擾帶捲過，底部有磁頭切換的雜訊；雜訊用 Blender 的 3D 柏林雜訊，Z 軸取自種子加上畫格
// @param amount float 0.7 0 1 "強度"
// @param bleed float 8 0 30 "色彩暈開"
// @param tracking float 0.5 0 1 "訊號干擾"
// @param noise float 0.3 0 1 "雜訊"
// @param seed float 0 0 100 "種子"

// Blender's perlin noise (Jenkins lookup3 hash + gradient noise), 3D: x and y are places on the tape,
// z is the moment (the seed plus the frame, a step of 0.77 per frame - never a whole number, where
// the noise is always 0), so every frame is a new, unrelated slice of the same noise
uint rotl(uint x, uint k) { return (x << k) | (x >> (32u - k)); }
void jfinal(inout uint a, inout uint b, inout uint c) {
    c ^= b; c -= rotl(b, 14u);
    a ^= c; a -= rotl(c, 11u);
    b ^= a; b -= rotl(a, 25u);
    c ^= b; c -= rotl(b, 16u);
    a ^= c; a -= rotl(c, 4u);
    b ^= a; b -= rotl(a, 14u);
    c ^= b; c -= rotl(b, 24u);
}
uint hash3(int x, int y, int z) {
    uint a, b, c; a = b = c = 0xdeadbeefu + (3u << 2u) + 13u;
    a += uint(x); b += uint(y); c += uint(z);
    jfinal(a, b, c); return c;
}
float nfade(float t) { return t * t * t * (t * (t * 6.0 - 15.0) + 10.0); }
float ngrad3(uint h, float x, float y, float z) {
    h &= 15u;
    float u = h < 8u ? x : y;
    float vt = (h == 12u || h == 14u) ? x : z;
    float v = h < 4u ? y : vt;
    return (((h & 1u) != 0u) ? -u : u) + (((h & 2u) != 0u) ? -v : v);
}
float gnoise3(vec3 p) {
    vec3 fl3 = floor(p);
    ivec3 i = ivec3(fl3);
    vec3 f = p - fl3;
    float u = nfade(f.x), v = nfade(f.y), w = nfade(f.z);
    float r = mix(
        mix(mix(ngrad3(hash3(i.x, i.y, i.z), f.x, f.y, f.z), ngrad3(hash3(i.x + 1, i.y, i.z), f.x - 1.0, f.y, f.z), u),
            mix(ngrad3(hash3(i.x, i.y + 1, i.z), f.x, f.y - 1.0, f.z), ngrad3(hash3(i.x + 1, i.y + 1, i.z), f.x - 1.0, f.y - 1.0, f.z), u), v),
        mix(mix(ngrad3(hash3(i.x, i.y, i.z + 1), f.x, f.y, f.z - 1.0), ngrad3(hash3(i.x + 1, i.y, i.z + 1), f.x - 1.0, f.y, f.z - 1.0), u),
            mix(ngrad3(hash3(i.x, i.y + 1, i.z + 1), f.x, f.y - 1.0, f.z - 1.0), ngrad3(hash3(i.x + 1, i.y + 1, i.z + 1), f.x - 1.0, f.y - 1.0, f.z - 1.0), u), v), w);
    return 0.9820 * r;
}

vec3 to_yiq(vec3 c) {
    return mat3(0.299, 0.596, 0.211, 0.587, -0.274, -0.523, 0.114, -0.322, 0.312) * c;
}
vec3 from_yiq(vec3 c) {
    return mat3(1.0, 1.0, 1.0, 0.956, -0.272, -1.106, 0.621, -0.647, 1.703) * c;
}

// noise of two sizes (the second one twice as fine, half as strong), about -1 .. 1
float fine(vec3 p) { return (gnoise3(p) + 0.5 * gnoise3(p * 2.03 + 11.7)) / 1.5; }

vec4 effect(vec2 uv) {
    float z = seed * 3.7 + float(frame) * 0.77 + 0.31;
    float row = floor(uv.y * resolution.y / 2.0);        // the tape's lines, 2 canvas px each
    vec2 px = uv * resolution;
    // every line slightly sideways (neighbouring lines drift together, then differ); more in the band
    // rolling down the picture and at the bottom
    float shift = fine(vec3(row * 0.45, 3.1, z)) * 1.6 * amount;
    float band = fract(time * 0.13 + 0.3);
    float in_band = exp(-pow((uv.y - band) / 0.03, 2.0)) * tracking;
    shift += (gnoise3(vec3(row * 0.8, 7.3, z)) * 1.4 + 0.3) * 24.0 * in_band;
    float bottom = smoothstep(0.96, 1.0, uv.y) * amount;
    shift += bottom * (18.0 + 22.0 * gnoise3(vec3(row * 0.6, 1.9, z)));
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

    // the grain is a streak along the line: long in x, a line high; the colour part is coarser and weaker
    vec3 g = vec3(fine(vec3(px.x / 5.0, row * 1.7, z + 20.0)));
    g += 0.35 * vec3(gnoise3(vec3(px.x / 14.0, row * 0.9, z + 40.0)), gnoise3(vec3(px.x / 14.0, row * 0.9, z + 60.0)),
                     gnoise3(vec3(px.x / 14.0, row * 0.9, z + 80.0)));
    tape += g * noise * 0.32;
    tape += smoothstep(0.55, 0.9, gnoise3(vec3(px.x / 3.0, row * 2.3, z + 100.0)) * 0.5 + 0.5) * in_band * 0.7;   // specks in the band
    float head = fine(vec3(px.x / 24.0, row * 2.0, z + 120.0)) * 0.5 + 0.5;       // the head switch: long bright smears
    tape = mix(tape, vec3(head * 1.2), bottom * 0.5);
    vec3 rgb = mix(a.rgb, clamp(tape, 0.0, 1.0) * a.a, amount);
    return vec4(rgb, a.a);
}
