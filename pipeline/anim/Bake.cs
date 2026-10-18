using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using UnityEditor;
using UnityEngine;
using UnityEngine.Animations;
using UnityEngine.Playables;

// Samples humanoid (muscle-space) clips on Xander and dumps every transform's local TRS per frame.
public static class Bake {
  static string F(float v) => v.ToString("0.######", CultureInfo.InvariantCulture);
  static void Q(StringBuilder sb, Quaternion q) { sb.Append(F(q.x)).Append(',').Append(F(q.y)).Append(',').Append(F(q.z)).Append(',').Append(F(q.w)); }
  static void V(StringBuilder sb, Vector3 v) { sb.Append(F(v.x)).Append(',').Append(F(v.y)).Append(',').Append(F(v.z)); }

  public static void Run() {
    string outDir = System.Environment.GetEnvironmentVariable("BAKE_OUT");
    Directory.CreateDirectory(outDir);
    var prefab = AssetDatabase.LoadAssetAtPath<GameObject>("Assets/Genies/Xander.fbx");
    var go = (GameObject)Object.Instantiate(prefab);
    go.transform.position = Vector3.zero; go.transform.rotation = Quaternion.identity;
    var anim = go.GetComponent<Animator>();
    if (anim == null) anim = go.AddComponent<Animator>();
    Debug.Log("BAKE avatar=" + (anim.avatar ? anim.avatar.name + " human=" + anim.avatar.isHuman : "none"));
    anim.applyRootMotion = false;
    anim.cullingMode = AnimatorCullingMode.AlwaysAnimate;
    anim.Rebind();
    bool useMode = System.Environment.GetEnvironmentVariable("BAKE_MODE") == "animmode";
    if (useMode) AnimationMode.StartAnimationMode();
    var all = new List<Transform>(go.GetComponentsInChildren<Transform>(true));

    var sb = new StringBuilder();
    sb.Append("{\"bones\":[");
    for (int i = 0; i < all.Count; i++) {
      var t = all[i];
      if (i > 0) sb.Append(',');
      sb.Append("{\"n\":\"").Append(t.name).Append("\",\"p\":").Append(t.parent ? all.IndexOf(t.parent) : -1).Append(",\"t\":[");
      V(sb, t.localPosition); sb.Append("],\"r\":["); Q(sb, t.localRotation); sb.Append("],\"s\":["); V(sb, t.localScale); sb.Append("]}");
    }
    sb.Append("]}");
    File.WriteAllText(Path.Combine(outDir, "rest.json"), sb.ToString());

    string folder = System.Environment.GetEnvironmentVariable("BAKE_FOLDER") ?? "Assets/Genies";
    string list = System.Environment.GetEnvironmentVariable("BAKE_CLIPS") ?? "Idle,Wave,Peace,Jump,Walk,Run";
    foreach (var name in list.Split(',')) {
      var clip = AssetDatabase.LoadAssetAtPath<AnimationClip>(folder + "/" + name + ".anim");
      if (clip == null) { Debug.LogError("BAKE missing " + name); continue; }
      var graph = PlayableGraph.Create("bake");
      graph.SetTimeUpdateMode(DirectorUpdateMode.Manual);
      var output = AnimationPlayableOutput.Create(graph, "out", anim);
      var play = AnimationClipPlayable.Create(graph, clip);
      play.SetApplyFootIK(true);
      output.SetSourcePlayable(play);
      graph.Play();
      int frames = Mathf.RoundToInt(clip.length * 30f) + 1;
      var o = new StringBuilder();
      o.Append("{\"name\":\"").Append(name).Append("\",\"length\":").Append(F(clip.length)).Append(",\"loop\":").Append(clip.isLooping ? "true" : "false")
       .Append(",\"human\":").Append(clip.isHumanMotion ? "true" : "false").Append(",\"frames\":[");
      for (int f = 0; f < frames; f++) {
        float tm = Mathf.Min(f / 30f, clip.length);
        if (useMode) {
          AnimationMode.BeginSampling();
          AnimationMode.SampleAnimationClip(go, clip, tm);
          AnimationMode.EndSampling();
        } else {
          play.SetTime(tm); play.SetTime(tm);
          graph.Evaluate(0f);
        }
        if (f > 0) o.Append(',');
        o.Append("{\"r\":[");
        for (int i = 0; i < all.Count; i++) { if (i > 0) o.Append(','); Q(o, all[i].localRotation); }
        o.Append("],\"t\":[");
        for (int i = 0; i < all.Count; i++) { if (i > 0) o.Append(','); V(o, all[i].localPosition); }
        o.Append("]}");
      }
      o.Append("]}");
      File.WriteAllText(Path.Combine(outDir, name + ".json"), o.ToString());
      graph.Destroy();
      Debug.Log("BAKE wrote " + name + " frames=" + frames + " hipsRot=" + all.Find(x => x.name == "Hips").localRotation.eulerAngles + " lhand=" + all.Find(x => x.name == "LeftHandIndex1").localRotation.eulerAngles);
    }
    if (useMode) AnimationMode.StopAnimationMode();
    Debug.Log("BAKE done");
  }
}
