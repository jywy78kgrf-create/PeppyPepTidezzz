# Resume the Boltz-2 held-out run (finish 26 -> 47)

The 26 already-scored compounds live in results/mmp1_boltz2_heldout.csv on the
RunPod network volume `evil_yellow_raccoon_volume` (CA-MTL-3). run_boltz_heldout.py
is resumable: it skips done compounds and scores only the remaining ~21.

1. Top up a few $ of RunPod credit.
2. Deploy a pod, ATTACHING the EXISTING volume `evil_yellow_raccoon_volume`
   (select it under "Persistent storage" -> do NOT "Automatically create").
   Pick a cheap GPU in CA-MTL-3 (RTX A4500 ~$0.26/hr, 20 GB VRAM, is plenty).
3. Rebuild the env (now one command -- cuEquivariance is in requirements-gpu.txt):
     cd /workspace/peppypeptidezzz
     git pull origin claude/nice-babbage-mpsl57
     PROFILE=gpu ./setup.sh --profile gpu          # ~12 min
4. Check the GPU; if cuda is False (torch built for a newer CUDA than the driver),
   install a matching CUDA build of torch (cu128 worked for a 12.8 driver):
     /opt/miniconda3/bin/conda run -n peppy-gpu python -c "import torch;print('cuda=',torch.cuda.is_available())"
     /opt/miniconda3/bin/conda run --no-capture-output -n peppy-gpu \
       python -m pip install --force-reinstall --index-url https://download.pytorch.org/whl/cu128 torch
5. Set engine + resume inside tmux (disconnect-safe):
     sed -i 's/^scorer: .*/scorer: boltz2/' peptidepipe/configs/mmp1_cosmetic/target.yaml
     tmux new -s boltz
     /opt/miniconda3/bin/conda run --no-capture-output -n peppy-gpu python run_boltz_heldout.py
   Detach: Ctrl+B then D. Reattach: tmux attach -t boltz.
6. When all 47 are done, held-out Spearman (pure-python, no deps):
     python3 -c "import csv,statistics as st;R=[r for r in csv.DictReader(open('results/mmp1_boltz2_heldout.csv')) if r['predicted'] not in ('','nan')];m=[float(r['measured']) for r in R];p=[float(r['predicted']) for r in R];rk=lambda v:[sorted(v).index(x)+1 if v.count(x)==1 else st.mean([i+1 for i,y in enumerate(sorted(v)) if y==x]) for x in v];sp=lambda a,b:(lambda ra,rb,n:sum((ra[i]-st.mean(ra))*(rb[i]-st.mean(rb)) for i in range(n))/((sum((x-st.mean(ra))**2 for x in ra)*sum((x-st.mean(rb))**2 for x in rb))**0.5))(rk(a),rk(b),len(a));print('n=',len(R),'held-out rho=',round(sp(m,p),4))"
7. Then run the leakage probe and TERMINATE the pod:
     /opt/miniconda3/bin/conda run -n peppy-gpu python leakage_probe.py results/mmp1_boltz2_heldout.csv

GO bar (pre-registered): held-out rho >= ~0.4, p < 0.01, AND survives the leakage
probe (novel-scaffold subset holds up). Below that = promising lead, not validated.
