#!/bin/bash
# Usage: capped.sh <seconds> <command> [args...]
# Runs the command in its own process group and kills the group at the deadline.
# AGY ignored the old exec-and-alarm limit, and a child probe ran for 3h13m.
set -eu
if [[ $# -lt 2 || ! $1 =~ ^[1-9][0-9]*$ || ! ${CAPPED_GRACE_SECONDS:-10} =~ ^[0-9]+$ ]]; then
  echo 'Usage: capped.sh <seconds> <command> [args...]' >&2
  exit 2
fi

exec perl -MPOSIX=setpgid -e '
  use strict;
  use warnings;
  my ($seconds, $grace) = splice @ARGV, 0, 2;
  my $pid = fork();
  die "capped: fork: $!\n" unless defined $pid;
  if ($pid == 0) {
    setpgid(0, 0) == 0 or die "capped: setpgid: $!\n";
    exec { $ARGV[0] } @ARGV or exit 127;
  }
  # Establish the group in either process, even if the child has yet to run.
  setpgid($pid, $pid);
  sub stop_group {
    my ($status) = @_;
    alarm 0;
    local $SIG{TERM} = "IGNORE";
    local $SIG{INT} = "IGNORE";
    kill "TERM", -$pid;
    sleep $grace if kill 0, -$pid;
    kill "KILL", -$pid;
    waitpid($pid, 0);
    exit $status;
  }
  $SIG{ALRM} = sub { print STDERR "capped: time limit reached after $seconds s\n"; stop_group(124) };
  $SIG{TERM} = sub { stop_group(143) };
  $SIG{INT} = sub { stop_group(130) };
  alarm $seconds;
  waitpid($pid, 0) == $pid or die "capped: waitpid: $!\n";
  my $status = $?;
  alarm 0;
  exit(($status & 127) ? 128 + ($status & 127) : $status >> 8);
' "$1" "${CAPPED_GRACE_SECONDS:-10}" "${@:2}"
