$basepath="."
$in_put="$basepath/Input"
$output="$basepath/Output"
$ffmpeg=Get-Command ffmpeg
if ($ffmpeg -eq $null) {
	$ffmpeg="$basepath/ffmpeg.exe"
}
$toconvert=Get-ChildItem "$in_put/"
$toconvert|%{
	$outfn=$_ -replace '\.[a-zA-Z0-9]+$','.wav'
	& $ffmpeg -i "$in_put/$_" -acodec pcm_s16le -ac 1 -ar 8000 "$output/$outfn"
}