function video(lifetime,video_id) {
    lifetime = null == lifetime ? 86400 : lifetime;
    const s = 1e6 * Math.floor(video_id / 1e6) + "/" + 1e3 * Math.floor(video_id / 1e3)
        , i = lifetime ? "json" : "jsond";
    return "/api/json/video/" + lifetime + "/" + s + "/" + video_id + "." + i
}
