#!/bin/sh
# Policy test: LEFT arm only, temporal ensembling, 30 deg/s, 20 s. Asks for "go" before torque.
cd ~/wax/repo && exec ../.venv/bin/python -u -m brain.arm.policy_run run ~/wax/models/act_dodge_bomba_nebius \
  --floor-z 0.082,0.055 --arms left --speed 30 --amp --seconds 20 \
  --cam top=/dev/video0 --cam left=/dev/video2 --cam right=/dev/video4
