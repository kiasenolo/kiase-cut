// @filter 顆粒
// @category 風格
// @description 底片雜訊，每一格都不一樣
// @param amount float 0.25 0 1 "強度"
// @param size float 1.5 1 8 "顆粒大小"
vec4 effect(vec2 uv) {
    vec4 c = src(uv);
    vec2 cell = floor(uv * resolution / size);
    float n = rand(cell + vec2(frame_phase().x * 13.1, frame_phase().x * 7.7) + frame_phase().y * vec2(0.37, 0.53)) - 0.5;
    return vec4(clamp(c.rgb + n * amount * c.a, 0.0, c.a), c.a);
}
