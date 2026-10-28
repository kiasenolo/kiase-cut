// @filter 移軸
// @category 模糊
// @description 只有一條帶子是清楚的，離它越遠越模糊，看起來像微縮模型
// @passes 2
// @param focus float 0.5 0 1 "清楚的位置"
// @param width float 0.15 0 1 "清楚的寬度"
// @param falloff float 0.3 0.01 1 "漸變距離"
// @param radius float 20 0 80 "最大模糊"
// @param angle float 0 -90 90 "角度"
// @param saturation float 1.2 0 2 "飽和度"

// how blurred (canvas px) the picture is at uv: 0 in the band, radius past its fade
float blur_at(vec2 uv) {
    float a = radians(angle);
    vec2 p = (uv - vec2(0.5, focus)) * vec2(resolution.x / resolution.y, 1.0);
    float dist = abs(-sin(a) * p.x + cos(a) * p.y);
    return radius * smoothstep(width * 0.5, width * 0.5 + falloff, dist);
}

vec4 effect(vec2 uv) {
    float r = blur_at(uv);
    vec4 c;
    if (r < 0.5) {
        c = src(uv);
    } else {
        // one direction of a Gaussian of that radius per pass (rows, then columns)
        vec2 px = (pass_index == 0 ? vec2(1.0, 0.0) : vec2(0.0, 1.0)) / resolution;
        float sigma = r / 2.0;
        float stride = max(1.0, r / 32.0);
        vec4 sum = vec4(0.0);
        float total = 0.0;
        for (int i = -32; i <= 32; i++) {
            float d = float(i) * stride;
            if (abs(d) > r) continue;
            float w = exp(-0.5 * d * d / (sigma * sigma));
            sum += src(uv + px * d) * w;
            total += w;
        }
        c = sum / total;
    }
    if (pass_index == 0) return c;
    c = unpremultiply(c);                            // toy-like colours
    float l = dot(c.rgb, vec3(0.299, 0.587, 0.114));
    return premultiply(vec4(clamp(mix(vec3(l), c.rgb, saturation), 0.0, 1.0), c.a));
}
