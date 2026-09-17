"""
WavMark Audio Communication Module
Clean implementation for audio text encoding/decoding using WavMark watermarking.
"""

import numpy as np
import soundfile as sf
import torch
import wavmark
import resampy

class EnhancedWavMark:
    """Enhanced WavMark for section-based encoding with higher capacity"""
    
    def __init__(self):
        self.device = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')
        self.model = wavmark.load_model().to(self.device)
        self.section_length = 16000  # 1 second at 16kHz
        self.pattern_length = 16     # Fixed pattern bits
        self.payload_length = 16     # User data bits per section
        # Fixed pattern for detection
        self.fixed_pattern = np.array([1, 1, 1, 1, 0, 0, 1, 0, 0, 1, 1, 1, 0, 1, 1, 0], dtype=int)
    
    def get_device_info(self):
        """Return device information"""
        return {
            'device': str(self.device),
            'cuda_available': torch.cuda.is_available(),
            'gpu_name': torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
        }
    
    def read_audio_mono_16k(self, path):
        """Load and convert audio to mono 16kHz"""
        signal, sr = sf.read(path)
        if signal.ndim > 1:
            signal = np.mean(signal, axis=1)
        if sr != 16000:
            signal = resampy.resample(signal, sr, 16000)
        return signal, 16000
    
    def calculate_capacity(self, audio_length_samples):
        """Calculate encoding capacity for audio"""
        num_sections = audio_length_samples // self.section_length
        total_bits = num_sections * self.payload_length
        
        return {
            'duration_seconds': audio_length_samples / 16000,
            'num_sections': num_sections,
            'total_bits': total_bits,
            'total_bytes': total_bits // 8,
            'max_characters': total_bits // 8
        }
    
    def encode_multiple_payloads(self, audio_path, payloads, output_path):
        """Encode bit array payloads into audio sections"""
        signal, sr = self.read_audio_mono_16k(audio_path)
        capacity = self.calculate_capacity(len(signal))
        
        # Validate inputs
        if not payloads:
            raise ValueError("No payloads provided")
        if len(payloads) > capacity['num_sections']:
            raise ValueError(f"Too many payloads: {len(payloads)} > {capacity['num_sections']}")
        
        watermarked_sections = []
        successful = 0
        failed = 0
        
        # Encode only the provided payloads
        for i in range(len(payloads)):
            start_idx = i * self.section_length
            end_idx = start_idx + self.section_length
            section = signal[start_idx:end_idx]
            
            # Prepare payload
            payload = np.array(payloads[i][:self.payload_length], dtype=int)
            if len(payload) < self.payload_length:
                payload = np.pad(payload, (0, self.payload_length - len(payload)))
            
            try:
                # Encode section
                watermark = np.concatenate([self.fixed_pattern, payload])
                with torch.no_grad():
                    signal_tensor = torch.FloatTensor(section).to(self.device)[None]
                    message_tensor = torch.FloatTensor(watermark).to(self.device)[None]
                    watermarked_tensor = self.model.encode(signal_tensor, message_tensor)
                    watermarked_section = watermarked_tensor.detach().cpu().numpy().squeeze()
                
                watermarked_sections.append(watermarked_section)
                successful += 1
            except Exception as e:
                watermarked_sections.append(section)
                failed += 1
        
        # Add remaining unmodified audio sections
        remaining_start = len(payloads) * self.section_length
        if remaining_start < len(signal):
            watermarked_sections.append(signal[remaining_start:])
        
        # Save result
        final_audio = np.concatenate(watermarked_sections)
        sf.write(output_path, final_audio, sr)
        
        return {
            'output_file': output_path,
            'successful_sections': successful,
            'failed_sections': failed,
            'total_sections': len(payloads)
        }
    
    def decode_multiple_payloads(self, audio_path):
        """Decode bit array payloads from audio sections"""
        signal, sr = self.read_audio_mono_16k(audio_path)
        capacity = self.calculate_capacity(len(signal))
        
        decoded_payloads = []
        section_stats = []
        
        for i in range(capacity['num_sections']):
            start_idx = i * self.section_length
            end_idx = start_idx + self.section_length
            
            # Handle short sections at the end
            if end_idx > len(signal):
                section = signal[start_idx:]
                if len(section) < self.section_length // 2:
                    break
                section = np.pad(section, (0, self.section_length - len(section)))
            else:
                section = signal[start_idx:end_idx]
            
            try:
                # Decode section
                with torch.no_grad():
                    signal_tensor = torch.FloatTensor(section).to(self.device).unsqueeze(0)
                    decoded_watermark = (self.model.decode(signal_tensor) >= 0.5).int()
                    decoded_watermark = decoded_watermark.detach().cpu().numpy().squeeze()
                
                # Extract pattern and payload
                decoded_pattern = decoded_watermark[:self.pattern_length]
                decoded_payload = decoded_watermark[self.pattern_length:self.pattern_length + self.payload_length]
                
                # Calculate confidence based on pattern match
                pattern_matches = np.sum(decoded_pattern == self.fixed_pattern)
                confidence = pattern_matches / self.pattern_length
                success = confidence > 0.75
                
                decoded_payloads.append(decoded_payload)
                section_stats.append({
                    'section': i,
                    'confidence': confidence,
                    'success': success
                })
                
            except Exception:
                # Add zero payload for failed sections
                decoded_payloads.append(np.zeros(self.payload_length, dtype=int))
                section_stats.append({
                    'section': i,
                    'confidence': 0.0,
                    'success': False
                })
        
        # Calculate summary statistics
        successful = sum(1 for s in section_stats if s['success'])
        avg_confidence = np.mean([s['confidence'] for s in section_stats]) if section_stats else 0
        
        return {
            'payloads': decoded_payloads,
            'section_stats': section_stats,
            'successful_sections': successful,
            'total_sections': len(section_stats),
            'success_rate': successful / len(section_stats) if section_stats else 0,
            'average_confidence': avg_confidence
        }

def text_to_payloads(text):
    """Convert text to 16-bit payloads with null terminator"""
    text_with_null = text + '\0'
    
    # Convert to bits
    message_bits = []
    for char in text_with_null:
        char_bits = format(ord(char), '08b')
        message_bits.extend([int(b) for b in char_bits])
    
    # Split into 16-bit chunks
    payloads = []
    for i in range(0, len(message_bits), 16):
        section_bits = message_bits[i:i+16]
        if len(section_bits) < 16:
            section_bits.extend([0] * (16 - len(section_bits)))
        payloads.append(np.array(section_bits, dtype=int))
    
    return payloads

def payloads_to_text(payloads):
    """Convert 16-bit payloads back to text"""
    # Reconstruct bits
    decoded_bits = []
    for payload in payloads:
        decoded_bits.extend(payload)
    
    # Convert to text
    decoded_text = ""
    for i in range(0, len(decoded_bits), 8):
        if i + 8 <= len(decoded_bits):
            byte_bits = decoded_bits[i:i+8]
            byte_value = int(''.join(map(str, byte_bits)), 2)
            
            # Stop at null terminator
            if byte_value == 0:
                break
            
            # Only printable ASCII
            if 32 <= byte_value <= 126:
                decoded_text += chr(byte_value)
    
    return decoded_text

def calculate_ber(original_text, decoded_text):
    """Calculate bit error rate between original and decoded text"""
    # Convert to bits
    orig_bits = []
    for char in original_text:
        orig_bits.extend([int(b) for b in format(ord(char), '08b')])
    
    dec_bits = []
    for char in decoded_text[:len(original_text)]:
        dec_bits.extend([int(b) for b in format(ord(char), '08b')])
    
    # Pad to same length
    max_bits = max(len(orig_bits), len(dec_bits))
    while len(orig_bits) < max_bits:
        orig_bits.append(0)
    while len(dec_bits) < max_bits:
        dec_bits.append(0)
    
    # Calculate errors
    bit_errors = sum(1 for i in range(max_bits) if orig_bits[i] != dec_bits[i])
    char_errors = sum(1 for i in range(min(len(original_text), len(decoded_text))) 
                     if original_text[i] != decoded_text[i])
    
    return {
        'bit_errors': bit_errors,
        'total_bits': max_bits,
        'ber_percentage': (bit_errors / max_bits) * 100 if max_bits > 0 else 100,
        'char_errors': char_errors,
        'total_chars': max(len(original_text), len(decoded_text)),
        'char_accuracy': ((min(len(original_text), len(decoded_text)) - char_errors) / 
                         max(len(original_text), len(decoded_text)) * 100) if max(len(original_text), len(decoded_text)) > 0 else 0,
        'perfect_match': original_text == decoded_text
    }