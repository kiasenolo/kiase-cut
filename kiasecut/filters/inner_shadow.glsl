// @filter Inner Shadow
// @category 風格
// @description 內陰影：從不透明部分的邊緣往內的一圈顏色，可以模糊、位移（在線性光裡運算）
// @passes 5
// @param color color #000000 "顏色"
// @param size int 6 -60 60 "大小"
// @param blur vec2 2,2 0 20 "模糊"
// @param offset vec2 0,0 -1000 1000 "位移"

// Passes: 0-1 the distance (canvas px) to the nearest see-through pixel, rows then columns, which
// makes the band exact for any size at about 2 x size reads a pixel; 2-3 the blur, rows then
// columns; 4 the coloured band, moved, over the picture and only where the picture is.
#define MAXD 64.0

vec3 srgb_to_lin(vec3 c) { return mix(c / 12.92, pow((c + 0.055) / 1.055, vec3(2.4)), step(vec3(0.04045), c)); }
vec3 lin_to_srgb(vec3 c) { c = clamp(c, 0.0, 1.0); return mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, step(vec3(0.0031308), c)); }

bool outside(vec2 p) { return p.x < 0.0 || p.y < 0.0 || p.x > 1.0 || p.y > 1.0; }

// what grows inwards: the see-through part (outside the picture too, as in Blender)
float shape(vec2 p) { return outside(p) ? 1.0 : 1.0 - original(p).a; }

// one direction of a Gaussian of sigma = r / 3 cut at r (Blender's blur), on channel r
float gauss(vec2 uv, vec2 dir, float r, float stp) {
    if (r < 0.25) return src(uv).r;
    float sum = 0.0, total = 0.0, k = 4.5 / (r * r);
    for (int i = -64; i <= 64; i++) {
        float d = float(i) * stp;
        if (abs(d) > r) continue;
        float w = exp(-k * d * d);
        sum += src(uv + dir * d / resolution).r * w;
        total += w;
    }
    return sum / total;
}

vec4 effect(vec2 uv) {
    float r = abs(float(size));
    bool grow = size > 0;
    // canvas px between two pixels of the picture worked on (more than 1 in a small preview): the step of every loop
    float stp = max(1.0, resolution.x / float(textureSize(source, 0).x));
    if (pass_index == 0) {
        if (r < 0.5) return vec4(shape(uv));
        float best = MAXD;                    // nearest pixel along the row that is in (grow) / out (shrink)
        for (int i = -64; i <= 64; i++) {
            float d = float(i) * stp;
            if (abs(d) > r + 1.0) continue;
            if ((shape(uv + vec2(d / resolution.x, 0.0)) >= 0.5) == grow) best = min(best, abs(d));
        }
        return vec4(best / MAXD);
    }
    if (pass_index == 1) {
        if (r < 0.5) return src(uv);
        float best = MAXD * MAXD;
        for (int i = -64; i <= 64; i++) {
            float d = float(i) * stp;
            if (abs(d) > r + 1.0) continue;
            float f = src(uv + vec2(0.0, d / resolution.y)).r * MAXD;
            best = min(best, f * f + d * d);
        }
        float dist = sqrt(best);
        return vec4(grow ? clamp(r + 1.0 - dist, 0.0, 1.0) : clamp(dist - r, 0.0, 1.0));
    }
    if (pass_index == 2) return vec4(gauss(uv, vec2(1.0, 0.0), blur.x, stp));
    if (pass_index == 3) return vec4(gauss(uv, vec2(0.0, 1.0), blur.y, stp));

    vec2 p = uv - offset / resolution;
    float m = outside(p) ? 0.0 : src(p).r;
    vec4 o = vec4(srgb_to_lin(color.rgb), 1.0) * color.a * m;           // the band, linear, premultiplied
    vec4 s = unpremultiply(original(uv));
    vec4 c = vec4(srgb_to_lin(s.rgb) * s.a, s.a);
    c = vec4(o.rgb * c.a + c.rgb * (1.0 - o.a), c.a);                  // over the picture, only where it is
    float a = clamp(c.a, 0.0, 1.0);
    vec3 rgb = a > 0.0 ? lin_to_srgb(c.rgb / a) * a : vec3(0.0);
    return vec4(min(rgb, vec3(a)), a);
}
